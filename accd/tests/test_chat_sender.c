/*
 * Player chat sender names: the full driver name while it fits in 35
 * code points, then the shorter forms, ASCII uppercase only.
 */

#define _POSIX_C_SOURCE 200809L

#include <signal.h>
#include <stdio.h>
#include <string.h>

#include "chat.h"
#include "state.h"

/* Defined in main.c, which the unit tests do not link. */
volatile sig_atomic_t g_stop;

static int failed;

static void
check(const char *first, const char *second, const char *last,
    const char *shortn, const char *want)
{
	struct DriverInfo d;
	char buf[CHAT_SENDER_SIZE];

	memset(&d, 0, sizeof(d));
	snprintf(d.first_name, sizeof(d.first_name), "%s", first);
	snprintf(d.second_name, sizeof(d.second_name), "%s", second);
	snprintf(d.last_name, sizeof(d.last_name), "%s", last);
	snprintf(d.short_name, sizeof(d.short_name), "%s", shortn);
	chat_sender_name(&d, buf, sizeof(buf));
	if (strcmp(buf, want) != 0) {
		fprintf(stderr, "FAIL: \"%s\" \"%s\" \"%s\": got \"%s\", "
		    "want \"%s\"\n", first, second, last, buf, want);
		failed = 1;
	}
}

int
main(void)
{
	/* Full name, with and without a second name. */
	check("Jean", "Pierre", "Dupont", "DUP", "JEAN PIERRE DUPONT");
	check("Smoke", "", "Test", "SMK", "SMOKE TEST");

	/* 35 code points still fit, 36 drop the second name. */
	check("Aaaaaaaaaa", "Bbbbbbbbbb", "Ccccccccccccc", "",
	    "AAAAAAAAAA BBBBBBBBBB CCCCCCCCCCCCC");
	check("Aaaaaaaaaa", "Bbbbbbbbbb", "Cccccccccccccc", "",
	    "AAAAAAAAAA CCCCCCCCCCCCCC");

	/* First and last too long: last name alone. */
	check("Aaaaaaaaaaaaaaaaaaaa", "", "Bbbbbbbbbbbbbbbbbbbb", "",
	    "BBBBBBBBBBBBBBBBBBBB");
	check("Aaaaaaaaaaaaaaaaaaaa", "Bb", "Bbbbbbbbbbbbbbbbbbbb", "",
	    "BBBBBBBBBBBBBBBBBBBB");

	/* Last name of 35 fits, 36 is cut to 32 plus "...". */
	check("Aa", "", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "",
	    "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB");
	check("Aa", "", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "",
	    "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB...");

	/* No last name: first name and the space are what gets cut. */
	check("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "", "", "",
	    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...");

	/* Only ASCII letters change case. */
	check("José", "", "Martínez", "", "JOSé MARTíNEZ");
	check("łukasz", "", "Żółć", "", "łUKASZ Żółć");

	/* Code points are counted, not bytes. */
	check("ÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖ", "", "üüüüüüüüüüüüüüüüü", "",
	    "ÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖ üüüüüüüüüüüüüüüüü");
	check("ÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖÖ", "", "üüüüüüüüüüüüüüüüüü", "",
	    "üüüüüüüüüüüüüüüüüü");
	check("𝔸𝔸𝔸𝔸𝔸𝔸𝔸𝔸", "x", "𝔹𝔹𝔹𝔹𝔹𝔹𝔹𝔹", "",
	    "𝔸𝔸𝔸𝔸𝔸𝔸𝔸𝔸 X 𝔹𝔹𝔹𝔹𝔹𝔹𝔹𝔹");

	/* A cut never splits a multibyte sequence. */
	check("a", "", "éééééééééééééééééééébbbbbbbbbbbbbbbbbbbb", "",
	    "ééééééééééééééééééééBBBBBBBBBBBB...");

	/* Missing names keep their separator, like the exe. */
	check("Max", "", "", "MAX", "MAX ");
	check("", "", "Verstappen", "VER", " VERSTAPPEN");
	check("", "Second", "", "SEC", " SECOND ");

	/* No name at all: short name, then "<anon>". */
	check("", "", "", "SMK", "SMK");
	check("", "", "", "", "<anon>");

	if (failed)
		return 1;
	printf("PASS: chat sender names\n");
	return 0;
}
