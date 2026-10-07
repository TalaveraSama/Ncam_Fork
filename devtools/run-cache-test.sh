#!/bin/sh
#
# NCam-NG cache engine test runner
#
# Builds and runs devtools/cache-engine-test.c, which links the real cache
# implementation (ncam-cache.c) with the hash table/list/time helpers of NCam.
# It needs nothing more than a host compiler, so the cache engine can be
# regression tested without cross compiling the whole daemon.
#
# Usage: devtools/run-cache-test.sh
#
set -e

NCAM_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${NCAM_ROOT}/devtools/.cache-test"

CC="${CC:-cc}"
CFLAGS="-O1 -g -Wall -I${NCAM_ROOT}"

mkdir -p "${BUILD_DIR}"

SOURCES="
	${NCAM_ROOT}/ncam-cache.c
	${NCAM_ROOT}/ncam-hashtable.c
	${NCAM_ROOT}/ncam-llist.c
	${NCAM_ROOT}/ncam-string.c
	${NCAM_ROOT}/ncam-time.c
	${NCAM_ROOT}/ncam-lock.c



	${NCAM_ROOT}/devtools/cache-engine-test.c
"

# shellcheck disable=SC2086
${CC} ${CFLAGS} ${SOURCES} -lpthread -o "${BUILD_DIR}/cache-engine-test"

"${BUILD_DIR}/cache-engine-test"
