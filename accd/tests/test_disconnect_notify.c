/*
 * conn_drop must send the 0x24 car disconnect to the remaining
 * clients for every driver that was accepted, including one whose
 * connection was already in CONN_DISCONNECT (kick, ban, send failure),
 * and stay silent for a connection rejected before it was accepted.
 */

#define _POSIX_C_SOURCE 200809L

#include <sys/socket.h>

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "msg.h"
#include "state.h"

/* Defined in main.c, which the unit tests do not link. */
volatile sig_atomic_t g_stop;

static int failed;

static void
check(const char *what, enum conn_state state, int accepted, int notify)
{
	struct Server *s;
	struct Conn *watcher, *leaving;
	struct sockaddr_in peer;
	unsigned char msg[8];
	ssize_t n;
	int sv[2];

	if ((s = calloc(1, sizeof(*s))) == NULL) {
		perror("calloc");
		exit(1);
	}
	server_init(s);
	s->max_connections = 4;
	if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == -1 ||
	    fcntl(sv[1], F_SETFL, O_NONBLOCK) == -1) {
		perror("socketpair");
		exit(1);
	}
	memset(&peer, 0, sizeof(peer));
	watcher = conn_new(s, sv[0], &peer);
	leaving = conn_new(s, -1, &peer);
	if (watcher == NULL || leaving == NULL) {
		fprintf(stderr, "conn_new failed\n");
		exit(1);
	}
	watcher->state = CONN_AUTH;
	leaving->state = state;
	leaving->authenticated_once = (uint8_t)accepted;
	leaving->car_id = 0;
	s->cars[0].used = 1;
	s->cars[0].car_id = ACC_CAR_ID_BASE;

	conn_drop(s, leaving);
	n = read(sv[1], msg, sizeof(msg));
	if (notify) {
		if (n != 5 || msg[0] != 3 || msg[1] != 0 ||
		    msg[2] != SRV_CAR_DISCONNECT_NOTIFY ||
		    (msg[3] | msg[4] << 8) != ACC_CAR_ID_BASE) {
			fprintf(stderr, "FAIL: %s: no 0x24 for car %d\n",
			    what, ACC_CAR_ID_BASE);
			failed = 1;
		}
	} else if (n != -1 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
		fprintf(stderr, "FAIL: %s: unexpected %zd bytes\n", what, n);
		failed = 1;
	}

	conn_drop(s, watcher);
	close(sv[1]);
	free(s);
}

int
main(void)
{
	check("authenticated driver", CONN_AUTH, 1, 1);
	check("driver already in teardown", CONN_DISCONNECT, 1, 1);
	check("rejected before accept", CONN_DISCONNECT, 0, 0);
	if (failed)
		return 1;
	printf("PASS: car disconnect sent for every accepted driver\n");
	return 0;
}
