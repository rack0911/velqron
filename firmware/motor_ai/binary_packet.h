#ifndef BINARY_PACKET_H
#define BINARY_PACKET_H

#include <Arduino.h>

/**
 * Packs motor telemetry into a dense 8-byte binary packet for LoRaWAN/Low-Bandwidth links.
 * Schema [8 Bytes]:
 * [0-1] Current (RMS) x 100 (uint16)
 * [2-3] Temperature x 10 (uint16)
 * [4]   Fuzzy Health Score (0-255)
 * [5]   Crest Factor x 10 (uint8)
 * [6]   Device Status Flags (uint8) -> [7:Tripped, 6:Overloaded, 5:Warning, 0-4:Reserved]
 * [7]   Checksum (XOR of bytes 0-6)
 */
void getBinaryPacket(uint8_t* buffer) {
    uint16_t packed_current = (uint16_t)(current * 100.0f);
    uint16_t packed_temp = (uint16_t)(temp * 10.0f);
    uint8_t packed_crest = (uint8_t)(crest_factor * 10.0f);
    
    uint8_t status_flags = 0;
    if (is_tripped) status_flags |= (1 << 7);
    if (is_overloaded) status_flags |= (1 << 6);
    if (health_status > 0) status_flags |= (1 << 5);

    buffer[0] = (packed_current >> 8) & 0xFF;
    buffer[1] = packed_current & 0xFF;
    buffer[2] = (packed_temp >> 8) & 0xFF;
    buffer[3] = packed_temp & 0xFF;
    buffer[4] = (uint8_t)(100.0f); // Placeholder for future learned health score
    buffer[5] = packed_crest;
    buffer[6] = status_flags;
    
    // XOR Checksum
    uint8_t checksum = 0;
    for(int i=0; i<7; i++) checksum ^= buffer[i];
    buffer[7] = checksum;
}

#endif // BINARY_PACKET_H
