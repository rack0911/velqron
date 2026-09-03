#ifndef FAL_CFG_H
#define FAL_CFG_H

#define FAL_DEV_NUM 1

/* partition table configuration */
#define FAL_PART_TABLE                                                               \
{                                                                                    \
    {FAL_PART_MAGIC_WORD, "fdb_tsdb1", "onchip_flash", 0, 1024 * 1024, 0},           \
}

#endif /* FAL_CFG_H */
