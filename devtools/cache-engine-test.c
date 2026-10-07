/*
 * NCam-NG cache engine test harness
 *
 * This program links against the real ncam-cache.c implementation (together
 * with the hash table/list/time helpers of NCam) and the small set of stubs
 * below, so that the cache logic can be exercised without building the whole
 * daemon (which requires a full cross toolchain and all external libraries).
 *
 * Usage:
 *      ./run-cache-test.sh          (see devtools/run-cache-test.sh)
 *
 * The harness covers:
 *      - cache insert / lookup / hit+miss accounting
 *      - control word update accounting
 *      - "hot entries" reporting (used by /ncamapi.json?part=cachestats)
 *      - capacity limit (cache_max_entries) with LRU eviction
 *      - max_cache_time expiry (cleanup_cache)
 *
 * Copyright (C) 2026 NCam-NG project
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#define MODULE_LOG_PREFIX "cachetest"

#include "globals.h"
#include "ncam-cache.h"
#include "ncam-chk.h"
#include "ncam-string.h"
#include "ncam-ecm.h"
#include "ncam-garbage.h"
#include "ncam-lock.h"
#include "ncam-time.h"
#include "module-cacheex.h"
#include "module-cw-cycle-check.h"

// NCam globals that normally live in the daemon
struct s_config cfg;
uint16_t cs_dblevel = 0;
char *LOG_LIST = "log_list";
uint8_t cacheex_peer_id[8] = { 0 };

// ---------------------------------------------------------------------------
// stubs replacing the parts of the daemon the cache engine talks to
// ---------------------------------------------------------------------------
static uint32_t stubs_cacheex_push = 0;

void cs_log_txt(const char *UNUSED(log_prefix), const char *fmt, ...)
{
	va_list args;
	va_start(args, fmt);
	vfprintf(stdout, fmt, args);
	va_end(args);
	fprintf(stdout, "\n");
}

void cs_log_hex(const char *UNUSED(log_prefix), const uint8_t *UNUSED(buf), int32_t UNUSED(n), const char *fmt, ...)
{
	va_list args;
	va_start(args, fmt);
	vfprintf(stdout, fmt, args);
	va_end(args);
	fprintf(stdout, "\n");
}

void add_garbage_debug(void *UNUSED(data), char *UNUSED(file), uint32_t UNUSED(line)) { }

void cacheex_cache_push(ECM_REQUEST *UNUSED(er)) { stubs_cacheex_push++; }

const char *username(struct s_client *UNUSED(client)) { return "cachetest"; }

bool check_client(struct s_client *cl) { return cl != NULL; }

uint8_t is_localreader(struct s_reader *UNUSED(rdr), ECM_REQUEST *UNUSED(er)) { return 0; }

uint16_t caidvaluetab_get_value(CAIDVALUETAB *UNUSED(cv), uint16_t UNUSED(caid), uint16_t default_value) { return default_value; }

int32_t chk_srvid_localgenerated_only_exception(ECM_REQUEST *UNUSED(er)) { return 0; }

uint8_t chk_lg_only(ECM_REQUEST *UNUSED(er), FTAB *UNUSED(ftab)) { return 0; }

uint8_t checkcwcycle(struct s_client *UNUSED(client), ECM_REQUEST *UNUSED(er), struct s_reader *UNUSED(reader), uint8_t *UNUSED(cw), int8_t UNUSED(rc), uint8_t UNUSED(cycletime_fr), uint8_t UNUSED(next_cw_cycle_fr))
{
	return 1; // cw cycle check passed
}

void ecm_cache_cleanup(bool UNUSED(force)) { }

CWCHECK get_cwcheck(ECM_REQUEST *UNUSED(er))
{
	CWCHECK cwcheck;
	memset(&cwcheck, 0, sizeof(cwcheck));
	return cwcheck;
}

int32_t format_ecm(ECM_REQUEST *UNUSED(ecm), char *result, size_t size)
{
	if(size)
		{ result[0] = '\0'; }
	return 0;
}

char *cs_inet_ntoa(IN_ADDR_T UNUSED(ip)) { return (char *)"0.0.0.0"; }

// ---------------------------------------------------------------------------
// test helpers
// ---------------------------------------------------------------------------
static uint32_t tests_run = 0;
static uint32_t tests_failed = 0;

static void check_true(const char *what, bool cond)
{
	tests_run++;
	if(!cond)
	{
		tests_failed++;
		printf("  [FAIL] %s\n", what);
	}
	else
	{
		printf("  [ ok ] %s\n", what);
	}
}

static ECM_REQUEST *make_ecm(uint32_t csp_hash, uint16_t caid, uint32_t prid, uint16_t srvid, uint8_t cw_seed)
{
	ECM_REQUEST *er = NULL;
	if(!cs_malloc(&er, sizeof(ECM_REQUEST)))
		{ exit(1); }

	er->csp_hash = csp_hash;
	er->caid = caid;
	er->prid = prid;
	er->srvid = srvid;
	er->rc = 1;             // E_FOUND
	er->ecm[0] = 0x80;      // odd
	er->ecm[1] = 0x00;
	for(uint8_t i = 0; i < 16; i++)
		{ er->cw[i] = (uint8_t)(cw_seed + i); }

	cs_ftime(&er->tps);
	return er;
}

void free_ecm(ECM_REQUEST *ecm)
{
	free(ecm);
}

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------
static void test_insert_and_lookup(void)
{
	printf("\n[test] insert / lookup / statistics\n");

	struct s_cache_stats st;
	init_cache();
	cache_reset_stats();

	ECM_REQUEST *er = make_ecm(0xAABBCCDD, 0x0100, 0x000001, 0x0001, 0x10);
	add_cache(er);

	check_true("cache size is 1 after the first insert", cache_size() == 1);

	ECM_REQUEST *hit = check_cache(er, NULL);
	check_true("lookup returns a cached answer", hit != NULL);
	check_true("cached control word matches", hit && memcmp(hit->cw, er->cw, 16) == 0);
	check_true("cached answer is flagged E_FOUND", hit && hit->rc == E_FOUND);
	if(hit)
		{ free(hit); }

	ECM_REQUEST *miss_er = make_ecm(0x11223344, 0x0100, 0x000001, 0x0002, 0x20);
	ECM_REQUEST *miss = check_cache(miss_er, NULL);
	check_true("unknown ecm is not answered from cache", miss == NULL);
	if(miss)
		{ free(miss); }

	cache_get_stats(&st);
	check_true("lookups counter is 2", st.lookups == 2);
	check_true("hits counter is 1", st.hits == 1);
	check_true("misses counter is 1", st.misses == 1);
	check_true("cw_entries counter is 1", st.cw_entries == 1);
	check_true("csp_entries counter is 1", st.csp_entries == 1);
	check_true("memory usage is reported", st.mem_bytes > 0);

	free_ecm(miss_er);
	free_ecm(er);
	free_cache();
}

static void test_cw_update_counting(void)
{
	printf("\n[test] control word update accounting and hot entries\n");

	struct s_cache_stats st;
	struct s_cache_top_entry top[8];
	init_cache();
	cache_reset_stats();

	ECM_REQUEST *er = make_ecm(0x00C0FFEE, 0x0500, 0x000002, 0x0100, 0x30);
	add_cache(er);
	add_cache(er);
	add_cache(er);

	ECM_REQUEST *hit = check_cache(er, NULL);
	if(hit)
		{ free(hit); }

	cache_get_stats(&st);
	check_true("only one control word was stored", st.cw_new == 1);
	check_true("repeated control words are counted as updates", st.cw_upd == 2);
	check_true("cacheex push was called for the new cw", stubs_cacheex_push > 0);

	uint32_t found = cache_get_top_entries(top, 8);
	check_true("hot entries report returns the entry", found == 1);
	check_true("hot entry has the expected caid", found == 1 && top[0].caid == 0x0500);
	check_true("hot entry has the expected srvid", found == 1 && top[0].srvid == 0x0100);
	check_true("hot entry counts the served cw", found == 1 && top[0].hits >= 3);

	free_ecm(er);
	free_cache();
}

static void test_capacity_and_lru(void)
{
	printf("\n[test] capacity limit (cache_max_entries) and LRU eviction\n");

	struct s_cache_stats st;
	init_cache();
	cache_reset_stats();

	cfg.cache_max_entries = 4;

	// fill the cache beyond its capacity
	for(uint32_t i = 0; i < 24; i++)
	{
		ECM_REQUEST *er = make_ecm(0x1000 + i, 0x0B00, 0x000003, (uint16_t)(0x2000 + i), (uint8_t)i);
		add_cache(er);
		free_ecm(er);
	}

	check_true("cache never grows over the configured limit", (int32_t)cache_size() <= cfg.cache_max_entries);

	// refresh one entry so that it becomes the most recently used one
	ECM_REQUEST *keep = make_ecm(0x1000 + 23, 0x0B00, 0x000003, 0x2000 + 23, 23);
	add_cache(keep);
	ECM_REQUEST *hit = check_cache(keep, NULL);
	check_true("recently used entry survives the eviction", hit != NULL);
	if(hit)
		{ free(hit); }

	cache_get_stats(&st);
	check_true("lru evictions are counted", st.evicted_lru > 0);
	check_true("cache is still usable after eviction", cache_size() > 0);

	free_ecm(keep);
	cfg.cache_max_entries = DEFAULT_CACHE_MAX_ENTRIES;
	free_cache();
}

static void test_history_and_helpers(void)
{
	printf("\n[test] metric history samples and size formatting\n");

	struct cache_history_sample history[CACHE_HISTORY_REPORTED];
	struct timeb times[CACHE_HISTORY_REPORTED];
	uint32_t count;

	init_cache();
	cache_reset_stats();

	check_true("no samples before recording", get_cache_history(history, times, 4) == 0);

	ECM_REQUEST *er = make_ecm(0x00FEED, 0x0E00, 0x000005, 0x0400, 0x50);
	add_cache(er);
	ECM_REQUEST *hit = check_cache(er, NULL);
	if(hit) { free(hit); }

	add_cache_history_sample();
	add_cache_history_sample();

	count = get_cache_history(history, times, 4);
	check_true("two samples are kept", count == 2);
	check_true("newest sample is returned first", count == 2 && times[0].time >= times[1].time);
	check_true("hit ratio is recorded", count == 2 && history[0].hit_ratio > 0);
	check_true("sample times are valid", count == 2 && times[0].time > 0);

	// the ring buffer must not overflow
	add_cache_history_sample();
	add_cache_history_sample();
	add_cache_history_sample();
	count = get_cache_history(history, times, 4);
	check_true("history is capped at the configured size", count == 4);
	check_true("requesting less than available works", get_cache_history(history, times, 2) == 2);

	// automatic sampling must respect the minimum interval
	uint32_t before = get_cache_history(history, times, CACHE_HISTORY_REPORTED);
	cache_history_sample_if_due(600);
	check_true("automatic sampling is throttled",
		get_cache_history(history, times, CACHE_HISTORY_REPORTED) == before);
	cache_history_sample_if_due(0);
	check_true("automatic sampling records when due",
		get_cache_history(history, times, CACHE_HISTORY_REPORTED) == before + 1);

	check_true("bytes are formatted", strcmp(cache_human_size(512), "512 B") == 0);
	check_true("kibibytes are formatted", strcmp(cache_human_size(2048), "2.0 KiB") == 0);
	check_true("mebibytes are formatted", strcmp(cache_human_size(3 * 1024 * 1024), "3.0 MiB") == 0);

	free_ecm(er);
	free_cache();
}

static void test_expiry(void)
{
	printf("\n[test] max_cache_time expiry\n");

	struct s_cache_stats st;
	init_cache();
	cache_reset_stats();

	cfg.max_cache_time = 1; // second
	ECM_REQUEST *er = make_ecm(0x00BADCAFE, 0x0D00, 0x000004, 0x0300, 0x40);
	add_cache(er);
	check_true("entry is stored", cache_size() == 1);

	cs_sleepms(1200);
	cleanup_cache(false);

	check_true("expired entry is removed", cache_size() == 0);
	cache_get_stats(&st);
	check_true("expired entries are counted", st.evicted_ttl > 0);

	free_ecm(er);
	free_cache();
}

int main(void)
{
	printf("NCam-NG cache engine test harness\n");
	printf("=================================\n");

	memset(&cfg, 0, sizeof(cfg));
	cfg.max_cache_time = 15;
	cfg.cache_max_entries = DEFAULT_CACHE_MAX_ENTRIES;

	test_insert_and_lookup();
	test_cw_update_counting();
	test_capacity_and_lru();
	test_history_and_helpers();
	test_expiry();

	printf("\n=================================\n");
	printf("%u checks, %u failed\n", tests_run, tests_failed);
	return tests_failed ? 1 : 0;
}
