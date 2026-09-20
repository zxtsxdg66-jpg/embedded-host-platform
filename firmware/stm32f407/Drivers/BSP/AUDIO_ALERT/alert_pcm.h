/**
 ****************************************************************************************************
 * @file        alert_pcm.h
 * @brief       三句告警语音的 PCM 数据表（存放于内部 Flash）。
 *
 * 数据本身在 alert_pcm.c 中，由 scripts/wav_to_c.py 从 WAV 文件生成：
 *
 *     python scripts/wav_to_c.py 温度.wav 湿度.wav 噪声.wav  *            -o firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/alert_pcm.c
 *
 * 格式要求（转换脚本会检查并自动重采样/转单声道）：
 *   - 16 kHz 采样率（与 audio_alert.h 的 AUDIO_ALERT_SAMPLE_RATE 一致）
 *   - 16 位有符号 PCM
 *   - 单声道（播放时由 audio_alert.c 复制到左右两声道）
 ****************************************************************************************************
 */
#ifndef __ALERT_PCM_H
#define __ALERT_PCM_H

#include <stdint.h>

typedef struct
{
    const int16_t *samples;   /* 单声道样本数组，NULL 表示该句尚无音频 */
    uint32_t sample_count;    /* 样本个数（不是字节数） */
} alert_clip_t;

/* 下标与 audio_alert.h 的 audio_alert_id_t 一一对应 */
extern const alert_clip_t g_alert_clips[];

#endif
