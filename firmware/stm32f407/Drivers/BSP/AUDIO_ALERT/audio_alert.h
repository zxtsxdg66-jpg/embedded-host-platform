/**
 ****************************************************************************************************
 * @file        audio_alert.h
 * @brief       语音告警播报 —— 播放预合成的固定告警语音，经板载 ES8388 + 板载扬声器输出。
 *
 * 方案选择（见 docs/05_Test/Project_Status_Context.md 5.9 节）：告警语音是**三句固定
 * 文案**，因此没有采用 TW-TTS 语音合成模块，而是把预先合成好的 PCM 直接编进固件、
 * 用板子自带的 ES8388 音频编解码器与板载扬声器播放。这样不额外挂任何模块——外挂
 * 模块的杜邦线在等待答辩的这段时间里是真实的物理故障源。
 *
 * 音频数据放在**内部 Flash**（alert_pcm.c 里的 const 数组），不用 SD 卡也不用外部
 * SPI Flash：三句各约 3 秒、16kHz/16bit 单声道合计约 288KB，而 STM32F407ZGT6 有 1MB
 * Flash（当前固件才用掉约 19KB）。省掉了文件系统、SPI Flash 驱动，也不必为了读字库
 * 而禁用 JTAG。代价是换文案要重新烧录固件——而文案本来就是固定的。
 *
 * 数据流：
 *   alert_pcm.c（Flash 中的单声道 PCM）
 *      → audio_alert_poll() 填充双缓冲（同时把单声道复制成左右两声道）
 *      → I2S + DMA（双缓冲循环模式，见 BSP/I2S）
 *      → ES8388 DAC → 板载扬声器
 *
 * 与噪声消隐的关系：喇叭放告警音会把噪声传感器读数顶上去，可能形成
 * “报警→播报→噪声升高→再报警”的正反馈。因此 main.c 在
 * audio_alert_is_playing() 为真期间**跳过噪声的 Modbus 请求**（不是读了丢弃），
 * 播完再延一个采集周期作为混响拖尾。
 ****************************************************************************************************
 */
#ifndef __AUDIO_ALERT_H
#define __AUDIO_ALERT_H

#include "./SYSTEM/sys/sys.h"
#include <stdint.h>

/* 三句固定告警语音。顺序必须与 alert_pcm.c 的 g_alert_clips[] 一致，
 * 也与 PC 端 service/alarm_announcer.py 的 AlertKind 一一对应。 */
typedef enum
{
    AUDIO_ALERT_TEMPERATURE = 0,
    AUDIO_ALERT_HUMIDITY,
    AUDIO_ALERT_NOISE,
    AUDIO_ALERT_COUNT
} audio_alert_id_t;

/* 播放采样率。alert_pcm.c 里的数据必须按同一采样率生成，
 * 由 scripts/wav_to_c.py 转换时保证。 */
#define AUDIO_ALERT_SAMPLE_RATE     16000u

/* 每个半缓冲的立体声帧数。16kHz 下 512 帧约 32ms，主循环 10ms 一拍，
 * 有充足余量在 DMA 用完前把下一块喂进去。 */
#define AUDIO_ALERT_HALF_FRAMES     512u

/**
 * @brief       初始化音频通路（IIC → ES8388 → I2S/DMA）
 * @retval      0 = 成功，非 0 = ES8388 初始化失败
 * @note        失败不应让整个固件停摆——传感器采集与 PC 链路要继续工作，
 *              只是没有声音。调用方据返回值决定是否打日志。
 */
uint8_t audio_alert_init(void);

/**
 * @brief       开始播报一句告警语音
 * @param       id : 语音编号
 * @retval      1 = 已开始播报；0 = 未播报（正在播、编号非法或该句无音频数据）
 * @note        正在播报时不打断、不排队——上位机侧已有 30 秒冷却与连续确认
 *              （service/alarm_announcer.py），到这里的播报请求本就稀疏。
 */
uint8_t audio_alert_play(audio_alert_id_t id);

/**
 * @brief       是否正在播报
 * @retval      1 = 正在播，0 = 空闲
 * @note        噪声消隐依据此标志，见本文件头部说明。
 */
uint8_t audio_alert_is_playing(void);

/**
 * @brief       立即停止播报
 */
void audio_alert_stop(void);

/**
 * @brief       喂缓冲。必须在主循环里持续调用
 * @note        DMA 中断只置标志、不搬数据（中断里应尽量短），实际的
 *              Flash → 缓冲区拷贝在这里完成。
 */
void audio_alert_poll(void);

#endif
