/* ---------------------------------------------------------------------------
 * NCam-NG :: mini-cliente newcamd525 para las pruebas de devtools/
 * (lo usa test-newcamd-multicaid.sh; no se instala en los paquetes)
 *
 * Reutiliza la cripto del propio daemon (module-newcamd-des.c) para que el
 * framing sea idéntico al real.
 *
 * Uso:
 *   ncd_test_client host port user md5crypt deskey-hex 'sid:caid:prid:ecmhex' [...]
 *
 * Hace login, pide el card data (lo imprime) y por cada spec manda una
 * petición ECM 0x80 con sid/caid/prid en la cabecera (estilo mgcamd; con
 * ceros imita a un cliente estilo oscam) e imprime la respuesta (CW o NAK).
 * md5crypt es crypt-md5 de la clave con salt "$1$abcdefgh$" (el que usa NCam).
 * ---------------------------------------------------------------------------
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/time.h>

#include "module-newcamd-des.h"

const int32_t CWS_NETMSGSIZE = 1024;

#define MSG_LOGIN     0xE0
#define MSG_LOGIN_ACK 0xE1
#define MSG_LOGIN_NAK 0xE2
#define MSG_CARD_REQ  0xE3
#define MSG_CARD_DATA 0xE4

static uint16_t msgid = 0;

static int hex2bin(const char *hex, uint8_t *out, int max)
{
	int n = strlen(hex) / 2, i;
	if(n > max) n = max;
	for(i = 0; i < n; i++)
	{
		unsigned v;
		sscanf(hex + 2 * i, "%2x", &v);
		out[i] = v;
	}
	return n;
}

static int read_full(int fd, uint8_t *buf, int len)
{
	int got = 0, n;
	while(got < len)
	{
		n = recv(fd, buf + got, len - got, 0);
		if(n <= 0) return -1;
		got += n;
	}
	return got;
}

/* send one 525 message from a raw message buffer (e.g. a raw ECM, whose
 * first byte is the command); hdr8 = sid/caid/prid header (zeros ok) */
static int ncd_send_raw(int fd, const uint8_t *msg, int mlen,
						const uint8_t *hdr8, uint8_t *key, int bump_id)
{
	static uint8_t netbuf[2048];
	int len;
	if(bump_id) msgid++;
	netbuf[0] = 0; netbuf[1] = 0;
	netbuf[2] = msgid >> 8; netbuf[3] = msgid & 0xFF;
	memcpy(netbuf + 4, hdr8, 8);
	memcpy(netbuf + 12, msg, mlen);
	len = 12 + mlen;
	len = nc_des_encrypt(netbuf, len, key);
	if(len < 0) return -1;
	netbuf[0] = (len - 2) >> 8;
	netbuf[1] = (len - 2) & 0xFF;
	return send(fd, netbuf, len, 0);
}

/* send one 525 message; hdr8 = sid/caid/prid header (zeros ok) */
static int ncd_send(int fd, uint8_t cmd, const uint8_t *data, int dlen,
					const uint8_t *hdr8, uint8_t *key, int bump_id)
{
	static uint8_t netbuf[2048];
	int len;
	if(bump_id) msgid++;
	netbuf[0] = 0; netbuf[1] = 0;
	netbuf[2] = msgid >> 8; netbuf[3] = msgid & 0xFF;
	memcpy(netbuf + 4, hdr8, 8);
	netbuf[12] = cmd;
	netbuf[13] = (dlen >> 8) & 0x0F;
	netbuf[14] = dlen & 0xFF;
	memcpy(netbuf + 15, data, dlen);
	len = 12 + 3 + dlen;
	len = nc_des_encrypt(netbuf, len, key);
	if(len < 0) return -1;
	netbuf[0] = (len - 2) >> 8;
	netbuf[1] = (len - 2) & 0xFF;
	return send(fd, netbuf, len, 0);
}

/* receive one message; returns cmd, sets dlen/data (data points into static buf) */
static int ncd_recv(int fd, uint8_t *key, uint8_t **data, int *dlen, int timeout_s)
{
	static uint8_t netbuf[2048];
	uint8_t l[2];
	struct timeval tv = { timeout_s, 0 };
	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	if(read_full(fd, l, 2) != 2) return -1;
	int n = (l[0] << 8) | l[1];
	if(n < 16 || n > 2000) return -1;
	netbuf[0] = l[0]; netbuf[1] = l[1];
	if(read_full(fd, netbuf + 2, n) != n) return -1;
	int len = nc_des_decrypt(netbuf, n + 2, key);
	if(len < 15) return -1;
	int dl = ((netbuf[13] & 0x0F) << 8) | netbuf[14];
	*data = netbuf + 15;
	*dlen = dl;
	return netbuf[12];
}

int main(int argc, char **argv)
{
	if(argc < 6)
	{
		fprintf(stderr, "usage: %s host port user md5crypt deskey-hex [sid:caid:prid:ecmhex ...]\n", argv[0]);
		return 2;
	}
	const char *host = argv[1];
	int port = atoi(argv[2]);
	const char *user = argv[3];
	const char *pwdcrypt = argv[4];
	uint8_t deskey[14];
	if(hex2bin(argv[5], deskey, 14) != 14) { fprintf(stderr, "bad deskey\n"); return 2; }

	int fd = socket(AF_INET, SOCK_STREAM, 0);
	struct sockaddr_in sa = { 0 };
	sa.sin_family = AF_INET;
	sa.sin_port = htons(port);
	inet_pton(AF_INET, host, &sa.sin_addr);
	if(connect(fd, (struct sockaddr *)&sa, sizeof(sa)) < 0) { perror("connect"); return 1; }

	uint8_t challenge[14];
	if(read_full(fd, challenge, 14) != 14) { fprintf(stderr, "no challenge\n"); return 1; }

	/* 1. login */
	uint8_t key[16], login[256];
	nc_des_login_key_get(challenge, deskey, 14, key);
	int ulen = strlen(user) + 1, plen = strlen(pwdcrypt) + 1;
	memcpy(login, user, ulen);
	memcpy(login + ulen, pwdcrypt, plen);
	uint8_t zero8[8] = { 0 };
	msgid = 0;
	if(ncd_send(fd, MSG_LOGIN, login, ulen + plen, zero8, key, 0) < 0)
	{ fprintf(stderr, "login send failed\n"); return 1; }

	uint8_t *data; int dlen;
	int cmd = ncd_recv(fd, key, &data, &dlen, 5);
	if(cmd == MSG_LOGIN_NAK) { printf("LOGIN_NAK\n"); return 1; }
	if(cmd != MSG_LOGIN_ACK) { printf("LOGIN unexpected reply %02X\n", cmd); return 1; }
	printf("LOGIN_ACK\n");

	/* 2. card data */
	nc_des_login_key_get(deskey, (uint8_t *)pwdcrypt, strlen(pwdcrypt), key);
	if(ncd_send(fd, MSG_CARD_REQ, NULL, 0, zero8, key, 1) < 0)
	{ fprintf(stderr, "card req failed\n"); return 1; }
	cmd = ncd_recv(fd, key, &data, &dlen, 5);
	if(cmd != MSG_CARD_DATA || dlen < 15) { printf("CARD_DATA unexpected %02X len %d\n", cmd, dlen); return 1; }
	uint16_t ccaid = (data[1] << 8) | data[2];
	printf("CARD_DATA caid=%04X nprids=%d prids=", ccaid, data[11]);
	for(int i = 0; i < data[11]; i++)
		printf("%s%02X%02X%02X", i ? "," : "", data[12 + 11 * i], data[13 + 11 * i], data[14 + 11 * i]);
	printf("\n");

	/* 3. ECMs */
	for(int a = 6; a < argc; a++)
	{
		unsigned sid, caid, prid;
		char ecmhex[1024];
		if(sscanf(argv[a], "%x:%x:%x:%1023s", &sid, &caid, &prid, ecmhex) != 4)
		{ fprintf(stderr, "bad ecm spec %s\n", argv[a]); continue; }
		uint8_t ecm[512];
		int elen = hex2bin(ecmhex, ecm, sizeof(ecm));
		/* like network_message_send: message length over ecm[1..2] */
		ecm[1] = (ecm[1] & 0xF0) | (((elen - 3) >> 8) & 0x0F);
		ecm[2] = (elen - 3) & 0xFF;
		uint8_t hdr[8] = { sid >> 8, sid & 0xFF, caid >> 8, caid & 0xFF,
							prid >> 16, (prid >> 8) & 0xFF, prid & 0xFF, 0 };
		if(ncd_send_raw(fd, ecm, elen, hdr, key, 1) < 0)
		{ printf("ECM %04X:%06X send failed\n", caid, prid); continue; }
		cmd = ncd_recv(fd, key, &data, &dlen, 8);
		if(cmd != 0x80 && cmd != 0x81) { printf("ECM %04X:%06X reply %02X len %d (UNEXPECTED)\n", caid, prid, cmd, dlen); continue; }
		if(dlen >= 16)
		{
			printf("ECM %04X:%06X CW=", caid, prid);
			for(int i = 0; i < 16; i++) printf("%02X", data[i]);
			printf("\n");
		}
		else
		{
			printf("ECM %04X:%06X NAK (dlen=%d)\n", caid, prid, dlen);
		}
	}
	close(fd);
	return 0;
}
