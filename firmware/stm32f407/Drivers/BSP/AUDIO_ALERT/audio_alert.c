/**
 ****************************************************************************************************
 * @file        audio_alert.c
 * @brief       语音告警播报实现，接口与设计说明见 audio_alert.h
 ****************************************************************************************************
 */

#include "./BSP/AUDIO_ALERT/audio_alert.h"
#include "./BSP/AUDIO_ALERT/alert_pcm.h"
#include "./BSP/ES8388/es8388.h"
#include "./BSP/I2S/i2s.h"
#include "./BSP/IIC/myiic.h"

/* 板载扬声器音量，ES8388 取值范围 0~33 */
#define AUDIO_ALERT_SPK_VOLUME      28u

/* 双缓冲：每个缓冲存 AUDIO_ALERT_HALF_FRAMES 个立体声帧，L/R 交替存放。
 * DMA 配置为 16 位对齐（见 BSP/I2S/i2s.c），因此传给 i2s_tx_dma_init() 的
 * “数据量”是半字个数 = 帧数 * 2。 */
static int16_t s_i2sbuf0[AUDIO_ALERT_HALF_FRAMES * 2];
static int16_t s_i2sbuf1[AUDIO_ALERT_HALF_FRAMES * 2];

static const int16_t *s_cursor;     /* 当前播放到的单声道样本位置 */
static uint32_t s_remaining;         /* 剩余单声道样本数 */
static volatile uint8_t s_playing;   /* 是否正在播报 */
static volatile uint8_t s_need_fill; /* DMA 中断置位：有半个缓冲空出来了 */
static volatile uint8_t s_fill_index;/* 该填哪一个缓冲：0 或 1 */
static uint8_t s_tail_fills;         /* 样本耗尽后又填了几次（纯静音）缓冲 */

/**
 * @brief       把一块单声道样本展开成立体声填进缓冲区
 * @note        数据不足时用静音（0）补齐——不足半个缓冲就停止播放的话，
 *              最后一小段会被截掉。
 */
static void audio_alert_fill(int16_t *dst)
{
    uint32_t i;

    for (i = 0; i < AUDIO_ALERT_HALF_FRAMES; i++)
    {
        int16_t sample = 0;

        if (s_remaining > 0u)
        {
            sample = *s_cursor;
            s_cursor++;
            s_remaining--;
        }

        dst[i * 2u]      = sample;   /* 左声道 */
        dst[i * 2u + 1u] = sample;   /* 右声道 */
    }
}

/**
 * @brief       I2S DMA 传输完成回调（在中断里执行，必须短）
 * @note        CT 位（DMA_SxCR 第 19 位）指示 DMA 当前正在用哪个缓冲：
 *              置位表示正在用 M1，说明 M0（缓冲 0）刚播完、可以重填。
 *              这一判定方式取自官方例程 wavplay.c 的 wav_i2s_dma_tx_callback()。
 */
static void audio_alert_dma_callback(void)
{
    if (DMA1_Stream4->CR & (1u << 19))
    {
        s_fill_index = 0u;
    }
    else
    {
        s_fill_index = 1u;
    }

    s_need_fill = 1u;
}

uint8_t audio_alert_init(void)
{
    uint8_t res;

    iic_init();                       /* ES8388 的配置总线（PB8/PB9） */
    res = es8388_init();
    if (res != 0u)
    {
        return res;                    /* 没有声音，但不影响采集与 PC 链路 */
    }

    es8388_i2s_cfg(0u, 3u);           /* 飞利浦标准 I2S，16 位数据长度 */
    es8388_adda_cfg(1u, 0u);          /* 开 DAC、关 ADC（本项目不录音） */
    es8388_output_cfg(1u, 1u);        /* 两路输出通道都打开 */
    es8388_spkvol_set(AUDIO_ALERT_SPK_VOLUME);

    i2s_init(I2S_STANDARD_PHILIPS, I2S_MODE_MASTER_TX, I2S_CPOL_LOW, I2S_DATAFORMAT_16B);
    i2s_samplerate_set(AUDIO_ALERT_SAMPLE_RATE);
    i2s_tx_dma_init((uint8_t *)s_i2sbuf0, (uint8_t *)s_i2sbuf1,
                     AUDIO_ALERT_HALF_FRAMES * 2u);
    i2s_tx_callback = audio_alert_dma_callback;

    s_playing = 0u;
    s_need_fill = 0u;
    return 0u;
}

uint8_t audio_alert_play(audio_alert_id_t id)
{
    const alert_clip_t *clip;

    if (s_playing != 0u)
    {
        return 0u;                     /* 正在播，不打断也不排队 */
    }
    if ((uint8_t)id >= (uint8_t)AUDIO_ALERT_COUNT)
    {
        return 0u;
    }

    clip = &g_alert_clips[id];
    if ((clip->samples == 0) || (clip->sample_count == 0u))
    {
        return 0u;                     /* 该句还没有音频数据（见 alert_pcm.c） */
    }

    s_cursor = clip->samples;
    s_remaining = clip->sample_count;

    /* 先把两个缓冲都填满再启动，避免开头播出一段未初始化的噪音 */
    audio_alert_fill(s_i2sbuf0);
    audio_alert_fill(s_i2sbuf1);
    s_need_fill = 0u;
    s_tail_fills = 0u;
    s_playing = 1u;

    i2s_play_start();
    return 1u;
}

void audio_alert_stop(void)
{
    if (s_playing == 0u)
    {
        return;
    }
    i2s_play_stop();
    s_playing = 0u;
    s_need_fill = 0u;
    s_remaining = 0u;
    s_tail_fills = 0u;
}

void audio_alert_poll(void)
{
    if (s_playing == 0u)
    {
        return;
    }

    if (s_need_fill == 0u)
    {
        return;                        /* DMA 还在放当前这半个缓冲 */
    }
    s_need_fill = 0u;

    /* 样本已经放完时，这一次填进去的整块都是静音。连续填满两块静音，
     * 说明最后一段有效音频必定已经被 DMA 送出，此时停止才不会截断尾音。
     *
     * 计数必须挂在“又完成了一次半缓冲传输”上，而不是挂在轮询次数上——
     * 主循环 10ms 一拍、而一个半缓冲有 32ms，按轮询计数会提前把声音掐掉。 */
    if (s_remaining == 0u)
    {
        s_tail_fills++;
    }

    audio_alert_fill((s_fill_index == 0u) ? s_i2sbuf0 : s_i2sbuf1);

    if (s_tail_fills >= 2u)
    {
        audio_alert_stop();
    }
}

uint8_t audio_alert_is_playing(void)
{
    return s_playing;
}
