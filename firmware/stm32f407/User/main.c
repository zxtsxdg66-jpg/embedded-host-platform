/**
 ****************************************************************************************************
 * @file        main.c
 * @brief       STM32F407 探索者V3 固件 —— 三传感器采集上报 + 通风 + 语音告警 + 板载 LCD
 *
 * 对应 docs/09_STM32Hardware/STM32F407_硬件落地方案.md 的开发路线，本文件已完成：
 *   LED/最小工程 -> USART1 -> PC握手 -> USART3 -> Modbus噪声传感器 -> 软件I2C -> AHT20 -> 三传感器数据统一上报
 * 全部七步的软件逻辑，以及其后扩展的通风风扇、语音告警播报、板载 2.8 寸 LCD 仪表盘。
 *
 * *** 验证状态（如实告知，不夸大）***
 * 本文件及其依赖的全部驱动模块均已完成实机验证：开发板与 AHT20 于 2026-08-16 到货
 * 并跑通温湿度两通道；HH_07.06 噪声传感器于 2026-08-18 到货，USART3/Modbus RTU 链路
 * 实机验证通过；2026-08-19 完成三通道 1 小时连续运行，共接收 3489 帧（每通道 1163
 * 帧），帧同步错误、丢帧、CRC 校验失败三项计数均为零，Modbus 应答成功率 100%。
 * 此前置信度最低的推断项——PB10/PB11 不装 P2 跳线能否作原始 TTL——亦已实测闭环。
 * 编译保持 0 Error / 0 Warning。PC 侧 src/ 在整个实机联调过程中零改动。
 *
 * *** 尚未实机验证的部分（同样如实告知）***
 * 上述验证覆盖的是三传感器采集上报这条主链路。其后扩展的三个模块——通风风扇
 * （PE5/PE6）、ES8388 语音告警播报、板载 2.8 寸 TFT LCD 仪表盘与电阻触摸——
 * 截至 2026-09-07 **只完成了编译（0 Error / 0 Warning）与静态核查，一次都还没有
 * 烧录到板子上运行过**（烧录器不在手边）。引脚占用、Keil 工程文件清单、HAL 依赖
 * 闭包均已逐项核对，但这些都不能替代实机。首次烧录后应按
 * docs/05_Test/Project_Status_Context.md 的验证清单逐项确认。
 * 另：语音数据当前仍是静音占位（alert_pcm.c 的 sample_count = 0），需先用
 * scripts/wav_to_c.py 生成真实音频再重新编译，否则播报流程会跑通但不出声。
 *
 * 已知缺陷（非致命，已列入改进方向）：Modbus 链路建立后的首次读数格式合法但测量
 * 尚未就绪，现有三层校验（长度/字段/CRC16）无法识别，需由上层丢弃首帧规避。
 *
 * 历史记录：本声明的上一版写于 2026-08-14 硬件到货之前，内容为"当前硬件尚未到货……
 * 并未、也不可能在没有真实传感器、真实总线电气环境的情况下完成实机验证"，当时
 * 仅完成了软件逻辑层面的实现与交叉核对（CRC32/CRC16/协议帧编码已用 Python 等价实现
 * 与 PC 端真实代码逐字节比对，帧结构/Modbus 请求响应格式已用厂商文档的真实报文示例
 * 核对）。该声明已于 2026-09-07 按实测结果更新。
 *
 * 采集周期状态机说明：
 *   噪声传感器通过 Modbus RTU 异步请求-应答（非阻塞，noise_sensor_poll() 每次
 *   main 循环调用一次，pc_link_poll() 不会被阻塞，PC 端命令仍能及时响应），
 *   AHT20 因软件 I2C 本身固有的阻塞式时序与传感器要求的测量延时，读取过程约
 *   80~100ms 是阻塞的——在噪声传感器结果落定（成功或超时）后才发起，每个采集
 *   周期只阻塞这一小段时间，不影响 PC 链路的整体响应性，也避免了为了让 AHT20
 *   读取"看起来异步"而引入不必要的复杂状态机。
 ****************************************************************************************************
 */

#include <stdio.h>
#include "./SYSTEM/sys/sys.h"
#include "./SYSTEM/delay/delay.h"
#include "./BSP/LED/led.h"
#include "./BSP/PC_LINK/pc_link.h"
#include "./BSP/NOISE_USART/noise_usart.h"
#include "./BSP/NOISE_SENSOR/noise_sensor.h"
#include "./BSP/AHT20/aht20.h"
#include "./BSP/FAN/fan.h"
#include "./BSP/AUDIO_ALERT/audio_alert.h"
#include "./BSP/UI_SCREEN/ui_screen.h"
#include "./BSP/SENSOR_DATA/sensor_data.h"
#include "./BSP/DEBUG_LOG/debug_log.h"

/* 与 scripts/run_gui.py --mode hardware 下 Hardware 设备的 wire id 约定一致 */
#define STM32_DEVICE_ID              1u

/* 采集周期：每隔多少个 10ms 主循环节拍触发一次完整的"读三个传感器 + 上报 PC"，
 * 300 * 10ms = 3 秒一次，满足 AHT20 说明书"采集周期应大于 1 秒"与噪声传感器
 * 400ms 内部刷新周期的要求，留有充分余量 */
#define SENSOR_CYCLE_INTERVAL_TICKS  300u

/* 语音播报结束后，噪声通道还要再消隐多久（10ms 一拍）。
 * 300 拍 = 3 秒 = 一个采集周期，用于让房间混响衰减掉——否则播报刚停就采样，
 * 读到的仍是喇叭的尾音。 */
#define NOISE_BLANK_TAIL_TICKS       300u

/* 屏幕上执行器状态（风扇/播报）与触摸的刷新间隔，10ms 一拍。10 拍 = 100ms，
 * 足够跟手，又不至于让显示与触摸占掉主循环太多时间。数值行不走这个节奏——
 * 它本来就只在每个采集周期结束时更新一次。 */
#define UI_REFRESH_INTERVAL_TICKS    10u

typedef enum
{
    CYCLE_IDLE = 0,       /* 等待下一个采集周期到来 */
    CYCLE_NOISE_WAIT,     /* 已发起噪声传感器 Modbus 请求，等待应答或超时 */
} sensor_cycle_state_t;

static void report_channel(const char *channel, float value)
{
    char payload[64];
    int payload_len = snprintf(payload, sizeof(payload),
                                "{\"channel\":\"%s\",\"value\":%.2f}",
                                channel, (double)value);

    if (payload_len > 0 && (size_t)payload_len < sizeof(payload))
    {
        pc_link_send_frame(STM32_DEVICE_ID, PROTOCOL_CMD_DATA_REPORT,
                            (const uint8_t *)payload, (uint16_t)payload_len);
    }
}

/**
 * @brief   噪声传感器结果已落定（成功或失败）后，补齐 AHT20 读数并统一上报三个通道
 */
static void finish_cycle_and_report(sensor_reading_t noise_reading)
{
    sensor_data_t data;
    aht20_status_t aht20_status;

    data.noise = noise_reading;
    if (!noise_reading.valid)
    {
        debug_log_printf("[noise] read failed\r\n");
    }

    aht20_status = aht20_read(&data.temperature.value, &data.humidity.value);
    if (aht20_status == AHT20_OK)
    {
        data.temperature.valid = 1u;
        data.humidity.valid = 1u;
    }
    else
    {
        data.temperature.valid = 0u;
        data.humidity.valid = 0u;
        debug_log_printf("[aht20] read failed, status=%d\r\n", (int)aht20_status);
    }

    if (data.temperature.valid)
    {
        report_channel("temperature", data.temperature.value);
    }
    if (data.humidity.valid)
    {
        report_channel("humidity", data.humidity.value);
    }
    if (data.noise.valid)
    {
        report_channel("noise", data.noise.value);
    }

    ui_screen_set_values(&data);   /* 板载 LCD 与 PC 端界面显示同一份读数 */

    LED1_TOGGLE();   /* 每完成一轮采集上报翻转一次 LED1，作为可见的运行节奏指示 */
}

static void handle_incoming_pc_frame(void)
{
    uint8_t device_id;
    uint8_t command_type;
    const uint8_t *payload;
    uint16_t payload_len;

    pc_link_take_frame(&device_id, &command_type, &payload, &payload_len);
    (void)device_id;

    /* 收到任何一帧都说明上位机确实在与本机通信，据此点亮屏幕上的链路状态。
     * 这里刻意**不做超时回落**：本链路的上位机只在状态变化时才下发命令，长时间
     * 没有下行帧是正常的稳态而不是掉线，用超时判断会误报。所以这个指示的准确
     * 含义是"已与上位机握手"，而不是"此刻链路仍然通畅"——固件目前没有能力区分
     * 后者（要区分得由 PC 周期性发心跳，代价是每个周期多一次命令往返，会挤占
     * 留给 Modbus 应答的等待窗口，暂不引入）。 */
    ui_screen_set_link(1u);

    if (command_type == PROTOCOL_CMD_DATA_REPORT || command_type == PROTOCOL_CMD_COMMAND_ACK)
    {
        return;   /* PC 不应下发这两种命令类型，收到则忽略 */
    }

    /* 通风控制。判定逻辑（阈值、迟滞、手动覆盖）全部在 PC 端
     * src/service/ventilation_controller.py 里，固件只负责执行——阈值因此只有一
     * 份、可在运行时调整，且改动措辞或阈值都不需要重新烧录固件。
     *
     * 上位机侧已做去重（只在期望状态变化时才下发），所以这里正常不会收到连续的
     * 重复命令；即便收到，fan_set() 是幂等的，重复置同一状态无副作用。 */
    if (command_type == PROTOCOL_CMD_FAN_ON)
    {
        fan_set(1u);
        debug_log_printf("[fan] ON\r\n");
    }
    else if (command_type == PROTOCOL_CMD_FAN_OFF)
    {
        fan_set(0u);
        debug_log_printf("[fan] OFF\r\n");
    }
    /* 语音告警。判定"何时该播报"（连续 2 个周期确认 + 30 秒冷却）全部在 PC 端
     * src/service/alarm_announcer.py，固件只负责放音。这样判定规则可以随时调整
     * 而不必重新烧录，固件里只有音频数据本身。
     *
     * audio_alert_play() 在正在播报时会直接返回 0（不打断、不排队），因此这里
     * 忽略返回值——上位机的冷却机制已经保证了播报请求足够稀疏。 */
    else if (command_type == PROTOCOL_CMD_ALERT_TEMPERATURE)
    {
        (void)audio_alert_play(AUDIO_ALERT_TEMPERATURE);
        debug_log_printf("[alert] temperature\r\n");
    }
    else if (command_type == PROTOCOL_CMD_ALERT_HUMIDITY)
    {
        (void)audio_alert_play(AUDIO_ALERT_HUMIDITY);
        debug_log_printf("[alert] humidity\r\n");
    }
    else if (command_type == PROTOCOL_CMD_ALERT_NOISE)
    {
        (void)audio_alert_play(AUDIO_ALERT_NOISE);
        debug_log_printf("[alert] noise\r\n");
    }
    /* 报警状态位图，只用于板载 LCD 每一行的"正常/报警"显示。阈值判定在 PC 端
     * src/service/sensor_data_processor.py，固件不重复实现一套阈值——否则同一套
     * GB 37488-2019 的论证会在 C 里出现第二份，并且悄悄与 PC 端分叉。
     *
     * 解析失败（键缺失或值非法）时保持上一次的显示不变：宁可显示旧状态，也不要
     * 因为一帧异常就把正在报警的行刷成"正常"。 */
    else if (command_type == PROTOCOL_CMD_ALERT_STATE)
    {
        uint32_t bits = 0u;

        if (protocol_payload_get_uint(payload, payload_len, "bits", &bits) != 0u)
        {
            ui_screen_set_alerts((uint8_t)bits);
            debug_log_printf("[alert] state bits=0x%02X\r\n", (unsigned int)bits);
        }
        else
        {
            debug_log_printf("[alert] state payload unparsable, display unchanged\r\n");
        }
    }
    /* 最近一条问答，供 LCD 第二页显示。与报警位图同理，判定全在 PC 端：
     * 固件收到的是"哪一类答案 + 数值"，用自己的模板画出来。
     *
     * 【为什么不下发文本】本板字库是从 ui_screen.c 的 UI_TXT 字面量生成的子集
     * （完整 GBK 要外挂 SPI Flash，其总线占 JTAG 引脚），画不出任意中文句子。
     * 附带好处是上位机那边模型改写措辞不会影响屏幕——屏上出现的永远是事实。
     *
     * kind 缺失就整条不采纳：那是唯一决定"画哪一种模板"的字段，缺了它其余数字
     * 无从解释。其余字段缺失按默认值处理，最差也只是少显示一项。 */
    else if (command_type == PROTOCOL_CMD_ANSWER_SHOW)
    {
        uint32_t kind = 0u;

        if (protocol_payload_get_uint(payload, payload_len, "kind", &kind) != 0u)
        {
            uint32_t channel = UI_ANSWER_CHANNEL_NONE;
            uint32_t value = 0u;
            uint32_t limit = 0u;
            uint32_t flags = 0u;
            uint32_t source = UI_ANSWER_SOURCE_LOCAL;

            (void)protocol_payload_get_uint(payload, payload_len, "channel", &channel);
            (void)protocol_payload_get_uint(payload, payload_len, "value", &value);
            (void)protocol_payload_get_uint(payload, payload_len, "limit", &limit);
            (void)protocol_payload_get_uint(payload, payload_len, "flags", &flags);
            (void)protocol_payload_get_uint(payload, payload_len, "source", &source);

            ui_screen_set_answer((uint8_t)kind, (uint8_t)channel, (uint16_t)value,
                                 (uint16_t)limit, (uint8_t)flags, (uint8_t)source);
            debug_log_printf("[answer] kind=%u ch=%u v=%u\r\n",
                             (unsigned int)kind, (unsigned int)channel,
                             (unsigned int)value);
        }
        else
        {
            debug_log_printf("[answer] payload has no kind, page unchanged\r\n");
        }
    }

    debug_log_printf("[pc] command 0x%02X received, replying ACK\r\n", command_type);

    {
        static const char ack_payload[] = "{\"status\":\"success\"}";
        pc_link_send_frame(STM32_DEVICE_ID, PROTOCOL_CMD_COMMAND_ACK,
                            (const uint8_t *)ack_payload, (uint16_t)(sizeof(ack_payload) - 1u));
    }
}

int main(void)
{
    uint32_t loop_ticks = 0;
    uint32_t next_cycle_tick = SENSOR_CYCLE_INTERVAL_TICKS;
    uint32_t noise_blank_until_tick = 0;   /* 噪声消隐窗口的结束节拍 */
    /* 「语音自检」按一次播一句，三句轮换，一个按钮就能覆盖全部告警语音 */
    audio_alert_id_t self_test_clip = AUDIO_ALERT_TEMPERATURE;
    sensor_cycle_state_t cycle_state = CYCLE_IDLE;
    aht20_status_t aht20_init_status;

    HAL_Init();                                       /* 初始化 HAL 库 */
    sys_stm32_clock_init(336, 8, 2, 7);               /* 设置时钟, 168MHz */
    delay_init(168);                                   /* 延时初始化 */
    led_init();                                        /* LED：系统存活/采集节奏指示 */
    fan_init();                                        /* 通风风扇（PE5/PE6），上电即停 */

    debug_log_init(DEBUG_LOG_DEFAULT_BAUDRATE);        /* USART2 调试日志（可选，未接线也不影响运行） */

    /* 板载 2.8 寸 LCD + 电阻触摸。放在 PC 链路之前初始化，是为了让屏幕尽早亮起来，
     * 上电后不至于长时间黑屏。
     *
     * 【首次上电会阻塞】24C02 里还没有触摸校准参数时，厂商的 tp_init() 会进入五点
     * 校准界面，等用户依次点完五个点才返回；这期间 PC 链路不被轮询。这是一次性的，
     * 校准值存进 24C02 后掉电不丢，之后每次上电都直接跳过。 */
    if (ui_screen_init() != 0u)
    {
        /* 与 AHT20、ES8388 同样的处理原则：某个外设缺失不让整机停摆。
         * 没有屏幕，采集、上报、风扇、语音一律照常。 */
        debug_log_printf("[lcd] not detected, running headless\r\n");
    }

    pc_link_init(PC_LINK_DEFAULT_BAUDRATE);            /* USART1：与 PC 的二进制协议链路 */
    noise_sensor_init(NOISE_USART_DEFAULT_BAUDRATE, NOISE_SENSOR_DEFAULT_ADDRESS);  /* USART3：噪声传感器 Modbus */

    if (audio_alert_init() != 0u)                      /* ES8388 + I2S：语音告警播报 */
    {
        /* 与 AHT20 同样的处理原则：某个外设不可用不应让整机停摆。
         * 没有声音，但采集、上报、风扇、PC 链路都继续正常工作。 */
        debug_log_printf("[audio] init failed, alerts will be silent\r\n");
    }

    aht20_init_status = aht20_init();                  /* 软件 I2C：AHT20 温湿度传感器 */
    if (aht20_init_status != AHT20_OK)
    {
        /* 初始化失败最常见的原因是尚未接线（当前硬件未到货，预期会失败），
         * 不在此处阻塞死循环——继续运行，噪声传感器与 PC 链路不应因为温湿度
         * 传感器暂时不可用而停摆；后续每个采集周期仍会尝试读取，接线后自然恢复 */
        debug_log_printf("[aht20] init failed, status=%d (expected until sensor is wired)\r\n",
                          (int)aht20_init_status);
    }

    debug_log_printf("\r\n[boot] STM32F407 firmware started, device_id=%u\r\n", STM32_DEVICE_ID);

    while (1)
    {
        pc_link_poll();

        if (pc_link_frame_ready())
        {
            handle_incoming_pc_frame();
        }

        /* 喂音频缓冲。DMA 中断只置标志，实际的 Flash→缓冲区拷贝在这里做。 */
        audio_alert_poll();

        /* 屏幕与触摸。每 UI_REFRESH_INTERVAL_TICKS 拍做一次，不必每拍都做——
         * 触摸的一次 SPI 采样带滤波要几百微秒，而人手按下的持续时间远长于 100ms，
         * 不会漏按。 */
        if ((loop_ticks % UI_REFRESH_INTERVAL_TICKS) == 0u)
        {
            ui_screen_set_actuators(fan_is_running(), audio_alert_is_playing());

            if (ui_screen_poll() == UI_EVENT_SELF_TEST)
            {
                /* 「语音自检」：本地按钮，不经过 PC。
                 *
                 * 它存在的理由是现场噪声很难自然超过 80dB，温湿度也不便临时改造，
                 * 演示时需要一个能确定性地让喇叭出声的入口。
                 *
                 * 刻意**不上报 PC**：自检不是告警，不该进告警日志、不该计入论文
                 * 第 9 章统计的告警次数，也不该消耗 PC 端 alarm_announcer 的 30 秒
                 * 冷却窗口——统计口径要干净，这与噪声消隐时"跳过 Modbus 请求"而
                 * 不是"请求了再丢掉"是同一个原则。
                 *
                 * 但它照样会触发噪声消隐：消隐的判据是 audio_alert_is_playing()，
                 * 与这段声音是谁请求的无关，喇叭一响噪声通道就该躲开。 */
                (void)audio_alert_play(self_test_clip);
                debug_log_printf("[alert] self-test clip=%d\r\n", (int)self_test_clip);

                self_test_clip = (audio_alert_id_t)((self_test_clip + 1) % AUDIO_ALERT_COUNT);
            }
        }

        /* 噪声消隐窗口：只要还在播报，就把窗口一直往后推；播报结束后再延
         * NOISE_BLANK_TAIL_TICKS 让混响衰减。放在播报判断之外单独维护，是为了
         * 让"播报中"和"刚播完"两种情况共用同一个判据（见 CYCLE_IDLE 分支）。 */
        if (audio_alert_is_playing() != 0u)
        {
            noise_blank_until_tick = loop_ticks + NOISE_BLANK_TAIL_TICKS;
        }

        switch (cycle_state)
        {
            case CYCLE_IDLE:
                if (loop_ticks >= next_cycle_tick)
                {
                    next_cycle_tick = loop_ticks + SENSOR_CYCLE_INTERVAL_TICKS;

                    if (loop_ticks < noise_blank_until_tick)
                    {
                        /* 噪声消隐中：喇叭正在放告警音（或刚放完、混响未散），
                         * 此刻读到的分贝值是喇叭自己的声音，不是环境噪声。
                         *
                         * 这里**跳过整个 Modbus 请求**，而不是照常请求再把结果丢掉。
                         * 两个原因：一是没必要占用总线；二是论文第 9 章统计的
                         * "Modbus 应答成功率"以发出的请求数为分母，跳过的周期
                         * 不进分母，指标口径才是干净的。
                         *
                         * 温湿度照常采集上报——喇叭不影响 AHT20。噪声通道
                         * valid=0，finish_cycle_and_report() 会自动不上报它，
                         * PC 侧无需任何改动。 */
                        sensor_reading_t skipped;
                        skipped.valid = 0u;
                        skipped.value = 0.0f;
                        finish_cycle_and_report(skipped);
                    }
                    else
                    {
                        noise_sensor_start_request();
                        cycle_state = CYCLE_NOISE_WAIT;
                    }
                }
                break;

            case CYCLE_NOISE_WAIT:
            {
                float noise_db = 0.0f;
                noise_sensor_status_t status = noise_sensor_poll(&noise_db);

                if (status == NOISE_SENSOR_PENDING)
                {
                    break;   /* 继续等待，本次循环不做其它事 */
                }

                {
                    sensor_reading_t noise_reading;
                    noise_reading.valid = (status == NOISE_SENSOR_OK) ? 1u : 0u;
                    noise_reading.value = noise_db;
                    finish_cycle_and_report(noise_reading);
                }

                cycle_state = CYCLE_IDLE;
                break;
            }

            default:
                cycle_state = CYCLE_IDLE;
                break;
        }

        loop_ticks++;
        if (loop_ticks % 30u == 0u)
        {
            LED0_TOGGLE();   /* 系统存活指示，沿用官方模板的闪烁节奏 */
        }

        delay_ms(10);
    }
}
