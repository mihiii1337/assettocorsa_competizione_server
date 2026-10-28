/*
 * Race overtime finish order: a lapped car crossing the line before
 * the leader keeps racing, the leader finishes on its crossing and
 * the lapped car then finishes on its next one. A finished car
 * crossing again must not end overtime while another car is still
 * racing, and every way overtime ends leaves the full postRaceSeconds.
 * Driven through the real 0x21 lap handler and session tick.
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
expect(int cond, const char *what)
{
	if (!cond) {
		fprintf(stderr, "FAIL: %s\n", what);
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
add_car(struct Server *s, int idx, int laps, int pos)
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
	car->race.lap_count = laps;
	car->race.position = (int16_t)pos;
	car->race.on_track = 1;
	car->rt.last_moved_ms = mono_ms();
	return c;
}

static struct Server *
race_in_overtime(void)
{
	struct Server *s;
	uint64_t now;
	int i;

	if ((s = calloc(1, sizeof(*s))) == NULL) {
		perror("calloc");
		exit(1);
	}
	server_init(s);
	s->max_connections = 4;
	s->session_count = 1;
	s->sessions[0].session_type = 10;
	s->sessions[0].duration_min = 20;
	s->session_overtime_s = 120;
	s->post_race_s = 15;

	/* Race clock ran out, leader on lap 10, the other car a lap down. */
	now = mono_ms();
	s->session.session_index = 0;
	s->session.ts_valid = 1;
	s->session.green_fired = 1;
	for (i = 0; i < 4; i++)
		s->session.ts[i] = now - 60000;
	s->session.ts[4] = now - 1;
	s->session.ts[5] = now + 120000;
	s->session.ts[6] = now + 135000;
	s->session.phase = PHASE_OVERTIME;
	s->session.overtime_hold = 1;
	s->session.cars_in_overtime = 2;
	s->session.overtime_leader_armed = 1;
	return s;
}

static void
check_finish_order(void)
{
	struct Server *s = race_in_overtime();
	struct Conn *leader, *lapped;

	leader = add_car(s, 0, 10, 1);
	lapped = add_car(s, 1, 9, 2);
	cross(s, lapped);
	expect(!s->cars[1].race.finished,
	    "lapped car finished before the leader");
	cross(s, leader);
	expect(s->cars[0].race.finished, "leader not finished");
	cross(s, leader);
	session_tick(s);
	expect(s->session.overtime_hold,
	    "second leader crossing ended overtime early");
	cross(s, lapped);
	expect(s->cars[1].race.finished,
	    "lapped car not finished after the leader");
	session_tick(s);
	expect(!s->session.overtime_hold,
	    "overtime kept open after every car finished");
	expect(s->session.advance_at_ms >= mono_ms() + 14000,
	    "no postRaceSeconds after every car finished");
	conn_drop(s, leader);
	conn_drop(s, lapped);
	free(s);
}

/*
 * The leader's finish moves the deadline to its crossing plus
 * sessionOverTimeSeconds, and reaching the deadline with a car still
 * out closes the race with the full postRaceSeconds.
 */
static void
check_deadline(void)
{
	struct Server *s = race_in_overtime();
	struct Conn *leader, *other;
	uint64_t t;

	leader = add_car(s, 0, 10, 1);
	other = add_car(s, 1, 10, 2);
	t = mono_ms();
	cross(s, leader);
	expect(s->session.ts[5] >= t + 120000,
	    "leader finish did not move the deadline");
	expect(s->session.ts[6] == s->session.ts[5] + 15000,
	    "aftercare not after the moved deadline");
	s->session.ts[5] = mono_ms() - 1;
	session_tick(s);
	expect(!s->session.overtime_hold, "deadline did not stop the race");
	expect(s->session.advance_at_ms >= mono_ms() + 14000,
	    "no postRaceSeconds after the deadline");
	conn_drop(s, leader);
	conn_drop(s, other);
	free(s);
}

int
main(void)
{
	check_finish_order();
	check_deadline();
	if (failed)
		return 1;
	printf("PASS: race overtime finish order and deadline\n");
	return 0;
}
