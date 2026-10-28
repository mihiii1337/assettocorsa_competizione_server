/*
 * When practice or qualifying reaches 0:00, a car out on its first
 * flying lap must keep its right to finish even though it has no
 * completed lap yet, while a car sitting in the pits must not hold
 * the session open.
 */

#define _POSIX_C_SOURCE 200809L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

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

static void
check(uint8_t type, const char *stype, int in_pit)
{
	struct Server *s;
	struct CarEntry *car;
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

	/* The session timer ran out a moment ago. */
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

	car = &s->cars[0];
	car->used = 1;
	car->race.lap_count = 0;
	car->race.on_track = !in_pit;
	car->race.in_pit = (uint8_t)in_pit;

	session_tick(s);
	if (in_pit) {
		expect(!s->session.overtime_hold,
		    "car in the pits held overtime open", stype);
	} else {
		expect(s->session.phase == PHASE_OVERTIME,
		    "not in overtime", stype);
		expect(s->session.overtime_hold, "no overtime hold", stype);
		expect(car->race.quali_eligible_to_finish,
		    "first flying lap not eligible", stype);
		expect(s->session.cars_in_overtime == 1,
		    "wrong eligible count", stype);
		session_quali_drop_eligibility(s, 0);
		expect(!s->session.overtime_hold,
		    "hold kept after the lap finished", stype);
	}
	free(s);
}

int
main(void)
{
	check(0, "practice", 0);
	check(4, "qualifying", 0);
	check(0, "practice in pit", 1);
	check(4, "qualifying in pit", 1);
	if (failed)
		return 1;
	printf("PASS: first flying lap keeps its right to finish\n");
	return 0;
}
