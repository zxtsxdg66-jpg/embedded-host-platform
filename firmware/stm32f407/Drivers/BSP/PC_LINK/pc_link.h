/**
 ****************************************************************************************************
 * @file        pc_link.h
 * @brief       STM32 <-> PC 通信驱动，运行在 USART1（PA9/PA10），经开发板板载 CH340C
 *              转 USB，与 PC 端 src/communication/serial.py 的 SerialChannel 对接。
 *
 * 职责边界（与 PC 端 application/hardware_runtime.py + frame_stream.py 的分工一致）：
 *   - 本模块负责"从任意字节流中拼出完整帧"（对应 PC 端 FrameStreamBuffer），
 *     以及"发送一帧"，即通信层 + 拼帧职责。
 *   - 具体帧内容的编解码交给 protocol_frame.c（对应 PC 端 protocol/decoder.py），
 *     本模块不重复实现 CRC/字段解析逻辑。
 *   - Payload 的业务含义（JSON 文本、具体字段）由上层（main.c 的 app_report /
 *     app_command 模块，第二阶段先直接写在 main.c 里）决定，本模块不关心。
 *
 * 中断安全设计：HAL_UART_RxCpltCallback（中断上下文）只做一件事——把收到的单字节
 * 推入一个小型环形缓冲区，不在中断里做任何拼帧/CRC 计算；真正的拼帧、CRC 校验、
 * 协议解析全部放在 pc_link_poll()（在 main 循环里被反复调用）里完成。这是标准的
 * "中断只做搬运、主循环做处理"模式，避免长时间占用中断上下文。
 ****************************************************************************************************
 */
#ifndef __PC_LINK_H
#define __PC_LINK_H

#include <stdint.h>
#include "./BSP/PROTOCOL/protocol_frame.h"

/* 与 PC 端 scripts/run_gui.py --mode hardware 默认波特率一致 */
#define PC_LINK_DEFAULT_BAUDRATE   115200u

/**
 * @brief   初始化 USART1（PA9/PA10）及其接收中断，并复位拼帧状态
 * @param   baudrate  波特率，需与 PC 端 --baudrate 参数一致
 */
void pc_link_init(uint32_t baudrate);

/**
 * @brief   驱动一次拼帧/解析处理，需在 main 循环中反复调用（不阻塞）
 * @note    每次调用最多处理缓冲区中已累积的字节，若凑齐一帧合法数据，会通过
 *          pc_link_frame_ready()/pc_link_take_frame() 让调用方取走
 */
void pc_link_poll(void);

/**
 * @brief   是否已有一帧解析完成、等待上层处理
 */
uint8_t pc_link_frame_ready(void);

/**
 * @brief   取出已就绪的一帧（调用后清除 ready 标志，缓冲区可继续接收下一帧）
 * @param   device_id       [出参]
 * @param   command_type    [出参]
 * @param   payload         [出参] 指向内部稳定缓冲区，在下一帧数据被取走（下一次
 *                          pc_link_take_frame() 成功取到新帧）之前始终有效
 * @param   payload_len     [出参]
 */
void pc_link_take_frame(uint8_t *device_id, uint8_t *command_type,
                         const uint8_t **payload, uint16_t *payload_len);

/**
 * @brief   发送一帧（阻塞发送，数据量小，不使用 DMA）
 * @retval  1=发送成功，0=编码失败（通常是 payload 超出内部发送缓冲区容量）
 */
uint8_t pc_link_send_frame(uint8_t device_id, uint8_t command_type,
                            const uint8_t *payload, uint16_t payload_len);

/**
 * @brief   统计：因帧头不匹配/CRC 校验失败而丢弃过的字节数（用于观测链路质量，
 *          对应 PC 端 HardwareDeviceReceiver.error_count 的固件侧对照量）
 */
uint32_t pc_link_get_error_count(void);

#endif
