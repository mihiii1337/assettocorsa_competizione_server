/*
 * The standings rank a driver who left with the connected ones: a
 * faster departed car stays ahead of a slower connected car instead
 * of keeping a stale position that collides with a live one, and a
 * departed car without a lap this session drops out with no position.
 */

#define _POSIX_C_SOURCE 200809L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

#include "session.h"
#include "state.h"

/* Defined in main.c, which the unit tests do not link. */
volatile sig_atomic_t g_stop;

static int failed;

static void
expect(int cond, const char *what, const char *stype)
{
	if (!cond) {
		fprintf(stderr, "FAIL: %s: %s\n", stype, what);
		failed = 1;
	}
}

static struct Server *
new_server(uint8_t type)
{
	struct Server *s;
	int i;

	if ((s = calloc(1, sizeof(*s))) == NULL) {
		perror("calloc");
		exit(1);
	}
	server_init(s);
	s->max_connections = 4;
	s->session_count = 1;
	s->sessions[0].session_type = type;
	s->session.session_index = 0;
	for (i = 0; i < 3; i++)
		s->cars[i].driver_count = 1;
	return s;
}

static void
check_timed(uint8_t type, const char *stype)
{
	struct Server *s = new_server(type);

	/* Connected car, 100 s best, still holding position 1. */
	s->cars[0].used = 1;
	s->cars[0].race.lap_count = 2;
	s->cars[0].race.best_lap_ms = 100000;
	s->cars[0].race.position = 1;
	/* Departed car, 90 s best, its old position collides. */
	s->cars[1].race.lap_count = 1;
	s->cars[1].race.best_lap_ms = 90000;
	s->cars[1].race.position = 1;
	/* Departed car without a lap this session. */
	s->cars[2].race.position = 2;

	session_recompute_standings(s);
	expect(s->cars[1].race.position == 1,
	    "faster departed car not first", stype);
	expect(s->cars[0].race.position == 2,
	    "slower connected car not second", stype);
	expect(s->cars[2].race.position == 0,
	    "departed car without a lap kept a position", stype);
	free(s);
}

static void
check_race(void)
{
	struct Server *s = new_server(10);

	s->cars[0].used = 1;
	s->cars[0].race.lap_count = 5;
	s->cars[0].race.position = 1;
	/* Departed a lap ahead. */
	s->cars[1].race.lap_count = 6;
	s->cars[1].race.position = 1;

	session_recompute_standings(s);
	expect(s->cars[1].race.position == 1 &&
	    s->cars[0].race.position == 2,
	    "departed car a lap ahead not ranked first", "race");
	free(s);
}

int
main(void)
{
	check_timed(0, "practice");
	check_timed(4, "qualifying");
	check_race();
	if (failed)
		return 1;
	printf("PASS: departed cars ranked with connected ones\n");
	return 0;
}
