/*
 * Practice and qualifying overtime: a car that has taken the flag
 * no longer holds the session open, even when it stays on track,
 * while a car still on its last lap does. Driven through the real
 * 0x21 lap handler and session tick.
 */

#define _POSIX_C_SOURCE 200809L

#include <sys/socket.h>

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "handlers.h"
#include "io.h"
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

/* 0x21 lap completed: u8 id, i32 lap ms, i32 ts, u8, u16 flags, u8. */
static void
cross(struct Server *s, struct Conn *c)
{
	unsigned char b[13];

	memset(b, 0, sizeof(b));
	b[0] = 0x21;
	b[1] = 0x90;	/* 90000 ms */
	b[2] = 0x5f;
	b[3] = 0x01;
	(void)h_sector_split_single(s, c, b, sizeof(b));
}

static struct Conn *
add_car(struct Server *s, int idx)
{
	struct sockaddr_in peer;
	struct CarEntry *car = &s->cars[idx];
	struct Conn *c;

	memset(&peer, 0, sizeof(peer));
	if ((c = conn_new(s, -1, &peer)) == NULL) {
		fprintf(stderr, "conn_new failed\n");
		exit(1);
	}
	c->state = CONN_AUTH;
	c->car_id = idx;
	car->used = 1;
	car->driver_count = 1;
	car->car_id = (uint16_t)(ACC_CAR_ID_BASE + idx);
	car->race.lap_count = 3;
	car->race.on_track = 1;
	return c;
}

static void
check(uint8_t type, const char *stype)
{
	struct Server *s;
	struct Conn *a, *b;
	uint64_t now;
	int i;

	if ((s = calloc(1, sizeof(*s))) == NULL) {
		perror("calloc");
		exit(1);
	}
	server_init(s);
	s->max_connections = 4;
	s->session_count = 1;
	s->sessions[0].session_type = type;
	s->sessions[0].duration_min = 10;
	s->session_overtime_s = 120;

	/* The session timer ran out a moment ago, both cars on track. */
	now = mono_ms();
	s->session.session_index = 0;
	s->session.phase = PHASE_SESSION;
	s->session.ts_valid = 1;
	s->session.green_fired = 1;
	for (i = 0; i < 4; i++)
		s->session.ts[i] = now - 60000;
	s->session.ts[4] = now - 1;
	s->session.ts[5] = now + 120000;
	s->session.ts[6] = now + 135000;
	a = add_car(s, 0);
	b = add_car(s, 1);
	session_tick(s);
	expect(s->session.overtime_hold, "no overtime hold", stype);

	/* A takes the flag and keeps driving, B is still on its lap. */
	cross(s, a);
	session_tick(s);
	expect(s->session.overtime_hold,
	    "hold released with a car still on its last lap", stype);

	/* B leaves the server, nobody is left to finish. */
	conn_drop(s, b);
	session_tick(s);
	expect(!s->session.overtime_hold,
	    "finished car on track held the session open", stype);

	conn_drop(s, a);
	free(s);
}

int
main(void)
{
	check(0, "practice");
	check(4, "qualifying");
	if (failed)
		return 1;
	printf("PASS: finished cars do not hold practice/qualifying open\n");
	return 0;
}
