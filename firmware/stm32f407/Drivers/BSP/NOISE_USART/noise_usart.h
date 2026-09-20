/**
 ****************************************************************************************************
 * @file        noise_usart.h
 * @brief       USART3（PB10=TX/PB11=RX）驱动，服务于噪声传感器 HH_07.06 的 Modbus RTU
 *              通信。与 pc_link.c（USART1）不同，本模块采用"RXNE 收字节 + IDLE 判定
 *              一帧结束"的方式，而不是按协议字段长度拼帧——这是 Modbus RTU 协议本身的
 *              标准做法：Modbus RTU 没有帧长度字段，标准规定以 3.5 个字符时间的总线
 *              空闲来界定一帧的结束（本实现用 STM32 USART 外设自带的 IDLE 中断，在
 *              收完一帧后总线空闲时硬件自动置位，效果等价且无需自行计时）。
 *
 * 直接操作 USART3 的 SR/DR 寄存器完成收发，不经过 HAL_UART_Receive_IT/
 * HAL_UART_RxCpltCallback 那一套（那是为 pc_link.c/USART1 准备的，按声明长度拼帧），
 * 避免两种拼帧语义混在一起、也避免与 HAL_UART_RxCpltCallback 的全局回调产生冲突。
 * GPIO/时钟/NVIC 初始化仍统一通过 HAL_UART_MspInit()（见 board_uart_msp.c）完成。
 ****************************************************************************************************
 */
#ifndef __NOISE_USART_H
#define __NOISE_USART_H

#include <stdint.h>

/* HH_07.06 出厂默认波特率，若已用配置工具改过，需要在此同步修改，
 * 见 docs/09_STM32Hardware/STM32F407_硬件落地方案.md D.4 节 */
#define NOISE_USART_DEFAULT_BAUDRATE   115200u

void noise_usart_init(uint32_t baudrate);

/**
 * @brief   发送一帧原始字节（Modbus 请求帧，含 CRC，由上层 noise_sensor.c 组好）
 */
void noise_usart_send(const uint8_t *data, uint16_t length);

/**
 * @brief   是否已收到一帧完整数据（USART3 IDLE 中断触发，代表总线静默、一帧结束）
 */
uint8_t noise_usart_frame_ready(void);

/**
 * @brief   取出已就绪的一帧原始字节（不做任何 Modbus 层面的解析/CRC 校验，
 *          由上层 noise_sensor.c 负责），取出后清除 ready 标志、缓冲区复位
 * @param   out_len  [出参] 实际字节数
 * @retval  指向内部缓冲区的指针，在下一次接收开始之前有效
 */
const uint8_t *noise_usart_take_frame(uint16_t *out_len);

/**
 * @brief   丢弃当前已缓存但尚未判定为"一帧"的数据并复位接收状态——用于主动超时后，
 *          放弃等待、准备发起下一次请求
 */
void noise_usart_reset_rx(void);

#endif
