/*
 * results_write leaves out a race that ended before its green flag,
 * like the exe, and still writes one that started.
 */

#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "results.h"
#include "state.h"

/* Defined in main.c, which the unit tests do not link. */
volatile sig_atomic_t g_stop;

/* Remove the .json files in results/, return how many there were. */
static int
results_files(void)
{
	DIR *d;
	struct dirent *e;
	char path[300];
	int n = 0;

	if ((d = opendir("results")) == NULL)
		return 0;
	while ((e = readdir(d)) != NULL) {
		if (strstr(e->d_name, ".json") == NULL)
			continue;
		snprintf(path, sizeof(path), "results/%s", e->d_name);
		(void)unlink(path);
		n++;
	}
	closedir(d);
	return n;
}

int
main(void)
{
	char dir[] = "tests/results_dump.XXXXXX";
	struct Server *s;
	int before, after, failed = 0;

	if (mkdtemp(dir) == NULL || chdir(dir) == -1) {
		perror(dir);
		return 1;
	}
	if ((s = calloc(1, sizeof(*s))) == NULL) {
		perror("calloc");
		return 1;
	}
	server_init(s);
	s->max_connections = 4;
	s->session_count = 1;
	s->sessions[0].session_type = 10;
	s->session.session_index = 0;

	(void)results_write(s);
	before = results_files();
	s->session.green_fired = 1;
	(void)results_write(s);
	after = results_files();
	if (before != 0) {
		fprintf(stderr, "FAIL: race before green was written\n");
		failed = 1;
	}
	if (after != 1) {
		fprintf(stderr, "FAIL: started race not written\n");
		failed = 1;
	}

	server_free(s);
	free(s);
	(void)rmdir("results");
	if (chdir("../..") == -1 || rmdir(dir) == -1)
		perror(dir);
	if (failed)
		return 1;
	printf("PASS: race before green leaves no results file\n");
	return 0;
}
