/**
 ****************************************************************************************************
 * @file        crc32.h
 * @brief       CRC-32/ISO-HDLC (即 zlib.crc32 / PNG / gzip / Ethernet FCS 所用的同一种 CRC-32)。
 *
 * 与 PC 端 src/protocol/encoder.py 的注释一致："4-byte CRC-32 (zlib.crc32, Python
 * standard library)"——本文件是同一算法的 C 语言实现，用于保证 STM32 固件与 PC 端
 * 对同一段字节计算出完全相同的 CRC 值。算法本身（多项式 0xEDB88320，反射输入/输出，
 * 初始值/结束异或均为 0xFFFFFFFF）是公开的标准算法，不依赖任何硬件手册或型号，因此
 * 未在 docs/08_YINGJIAN 资料中另行核实来源。
 ****************************************************************************************************
 */
#ifndef __CRC32_H
#define __CRC32_H

#include <stdint.h>

/**
 * @brief   计算一段数据的 CRC-32（与 Python zlib.crc32() 结果完全一致）
 * @param   data    数据起始地址
 * @param   length  数据长度（字节）
 * @retval  32 位 CRC 校验值
 */
uint32_t crc32_calculate(const uint8_t *data, uint32_t length);

#endif
