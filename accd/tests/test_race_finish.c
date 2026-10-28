/*
 * Race overtime finish order: a lapped car crossing the line before
 * the leader keeps racing, the leader finishes on its crossing and
 * the lapped car then finishes on its next one.  Driven through the
 * real 0x21 lap handler.
 */

#define _POSIX_C_SOURCE 200809L

#include <sys/socket.h>

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "handlers.h"
#include "io.h"
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
	return c;
}

int
main(void)
{
	struct Server *s;
	struct Conn *leader, *lapped;
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
	s->session.overtime_leader_armed = 1;
	leader = add_car(s, 0, 10, 1);
	lapped = add_car(s, 1, 9, 2);

	cross(s, lapped);
	expect(!s->cars[1].race.finished,
	    "lapped car finished before the leader");
	cross(s, leader);
	expect(s->cars[0].race.finished, "leader not finished");
	cross(s, lapped);
	expect(s->cars[1].race.finished,
	    "lapped car not finished after the leader");

	conn_drop(s, leader);
	conn_drop(s, lapped);
	free(s);
	if (failed)
		return 1;
	printf("PASS: lapped car takes the flag after the leader\n");
	return 0;
}
