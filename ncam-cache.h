#ifndef NCAM_CACHE_H_
#define NCAM_CACHE_H_

/* NCam-NG: internal cache engine statistics.
 * The counters are best effort values that are updated while serving requests.
 * They are meant for monitoring/logging and must never be used for decisions.
 */
struct s_cache_stats
{
	uint64_t lookups;        // check_cache() calls
	uint64_t hits;           // lookups answered from the internal cache
	uint64_t misses;         // lookups not answered from the internal cache
	uint64_t csp_entries;    // ECM containers currently stored
	uint64_t cw_entries;     // control words currently stored
	uint64_t cw_new;         // control words stored for the first time
	uint64_t cw_upd;         // already known control words seen again
	uint64_t cwc_rejected;   // control words dropped by the cw cycle check
	uint64_t evicted_ttl;    // containers removed because they were too old
	uint64_t evicted_lru;    // containers removed because of capacity limit
	uint64_t mem_bytes;      // estimated memory used by the internal cache
	uint64_t cache_serves;   // total ecm requests served from any cache layer
};

/* NCam-NG: one "hot" entry of the internal cache (used by the webif/api) */
struct s_cache_top_entry
{
	uint16_t caid;
	uint32_t prid;
	uint16_t srvid;
	uint32_t hits;           // how many times this control word was served
	uint8_t  from_csp;       // answered via csp
	uint8_t  from_cacheex;   // answered via cacheex peer
	uint8_t  from_localcards;// answered by a local card
};

// how many "hot" cache entries are reported by the webif/api
#define CACHE_TOP_ENTRIES_REPORTED 20

void cache_get_stats(struct s_cache_stats *st);
void cache_reset_stats(void);
uint32_t cache_get_top_entries(struct s_cache_top_entry *out, uint32_t max_entries);

/* NCam-NG: state of the optional "cw cache" used by cacheex (AIO feature) */
struct s_cw_cache_stats
{
	uint64_t entries;
	uint64_t mem_bytes;
	uint32_t localgenerated;
};

void init_cache(void);
#ifdef CS_CACHEEX_AIO
void init_cw_cache(void);
void cw_cache_get_stats(struct s_cw_cache_stats *st);
#endif
void free_cache(void);
void add_cache(ECM_REQUEST *er);
struct ecm_request_t *check_cache(ECM_REQUEST *er, struct s_client *cl);
void cleanup_cache(bool force);
void remove_client_from_cache(struct s_client *cl);
uint32_t cache_size(void);
#ifdef CS_CACHEEX_AIO
uint32_t cache_size_lg(void);
#endif
uint8_t get_odd_even(ECM_REQUEST *er);
uint8_t check_is_pushed(void *cw, struct s_client *cl);
#ifdef CS_CACHEEX_AIO
void cw_cache_cleanup(bool force);
int compare_csp_hash(const void *arg, const void *obj);
void cacheex_get_srcnodeid(ECM_REQUEST *er, uint8_t *remotenodeid);
#endif
#endif
