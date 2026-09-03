#ifndef SECURITY_H
#define SECURITY_H

#include <Arduino.h>
#include <mbedtls/md.h>

// --- SHARED SECRET (In production, this should be unique per device) ---
const char* SHARED_SECRET = "VELQRON_INDUSTRIAL_2026";

/**
 * Validates an HMAC-SHA256 signature for a command.
 * Expected format: <CMD>:<VALUE>:<SIG_HEX_4_CHARS>
 */
bool validateCommandSignature(String cmd_str) {
    int first_colon = cmd_str.indexOf(':');
    int last_colon = cmd_str.lastIndexOf(':');
    
    if (first_colon == -1 || last_colon == -1 || first_colon == last_colon) {
        // Not a signed command format
        return false;
    }

    String payload = cmd_str.substring(0, last_colon);
    String provided_sig = cmd_str.substring(last_colon + 1);

    uint8_t hmac_result[32];
    mbedtls_md_context_t ctx;
    mbedtls_md_type_t md_type = MBEDTLS_MD_SHA256;

    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(md_type), 1);
    mbedtls_md_hmac_starts(&ctx, (const unsigned char*) SHARED_SECRET, strlen(SHARED_SECRET));
    mbedtls_md_hmac_update(&ctx, (const unsigned char*) payload.c_str(), payload.length());
    mbedtls_md_hmac_finish(&ctx, hmac_result);
    mbedtls_md_free(&ctx);

    // Truncate to 4-character hex signature for lightweight edge verification
    char hex_sig[5];
    sprintf(hex_sig, "%02x%02x", hmac_result[0], hmac_result[1]);

    if (provided_sig.equalsIgnoreCase(String(hex_sig))) {
        return true;
    }
    
    Serial.printf("SEC_ERR: Sig Mismatch. Expected: %s, Got: %s\n", hex_sig, provided_sig.c_str());
    return false;
}

#endif // SECURITY_H
