/**
 ****************************************************************************************************
 * @file        pc_link.c
 ****************************************************************************************************
 */
#include "pc_link.h"
#include "./SYSTEM/sys/sys.h"

/* ------------------------------------------------------------------------ */
/* USART1 (PA9=TX / PA10=RX) 引脚与外设定义
 * 与 docs/hardware.md D.1/D.6 节一致：
 * USART1 经开发板 P10 跳线默认接板载 CH340C（USB_UART 口），无需额外接线。 */
#define PC_LINK_TX_GPIO_PORT            GPIOA
#define PC_LINK_TX_GPIO_PIN             GPIO_PIN_9
#define PC_LINK_RX_GPIO_PORT            GPIOA
#define PC_LINK_RX_GPIO_PIN             GPIO_PIN_10
#define PC_LINK_GPIO_AF                 GPIO_AF7_USART1
#define PC_LINK_USART                   USART1
#define PC_LINK_USART_IRQn              USART1_IRQn
#define PC_LINK_USART_IRQHandler        USART1_IRQHandler

/* ISR -> 主循环 的单字节环形缓冲区，容量远大于单帧典型长度即可 */
#define PC_LINK_RING_CAPACITY           256u
/* 拼帧用的线性缓冲区，需能容纳一帧的最大长度；第二阶段 Payload 均为短 JSON 文本，
 * 256 字节留有充分余量，后续如需支持更大 Payload 再扩容 */
#define PC_LINK_ASSEMBLY_CAPACITY       256u
/* 发送缓冲区，同理 */
#define PC_LINK_SEND_CAPACITY           256u

static UART_HandleTypeDef s_uart_handle;

static volatile uint8_t s_ring_buf[PC_LINK_RING_CAPACITY];
static volatile uint16_t s_ring_head = 0;   /* ISR 写入位置 */
static volatile uint16_t s_ring_tail = 0;   /* 主循环读取位置 */
static uint8_t s_isr_rx_byte;               /* HAL_UART_Receive_IT 的单字节接收落点 */

static uint8_t s_assembly_buf[PC_LINK_ASSEMBLY_CAPACITY];
static uint16_t s_assembly_len = 0;

/* 就绪帧的 Payload 拷贝存放处：poll() 检测到一帧后会立刻把该帧（含 Payload）从
 * s_assembly_buf 中移出以继续接收后续字节，因此 Payload 必须在移出前拷贝到这里，
 * 否则 pc_link_take_frame() 返回的指针会指向已被覆盖的位置 */
static uint8_t s_frame_payload_buf[PC_LINK_ASSEMBLY_CAPACITY];

static uint8_t s_send_buf[PC_LINK_SEND_CAPACITY];

static uint32_t s_error_count = 0;

static uint8_t s_frame_ready = 0;
static uint8_t s_frame_device_id = 0;
static uint8_t s_frame_command_type = 0;
static uint16_t s_frame_payload_len = 0;

/* USART1 的 GPIO/时钟/NVIC 初始化统一在 Drivers/BSP/BOARD/board_uart_msp.c 的
 * HAL_UART_MspInit() 中完成——HAL 库该回调函数在整个工程里只能有一份定义，
 * USART1/USART3/USART2(调试口) 的引脚配置都汇总在那一处，避免在各自的驱动文件
 * 里重复定义导致链接冲突。 */

void pc_link_init(uint32_t baudrate)
{
    s_ring_head = 0;
    s_ring_tail = 0;
    s_assembly_len = 0;
    s_frame_ready = 0;
    s_error_count = 0;

    s_uart_handle.Instance = PC_LINK_USART;
    s_uart_handle.Init.BaudRate = baudrate;
    s_uart_handle.Init.WordLength = UART_WORDLENGTH_8B;
    s_uart_handle.Init.StopBits = UART_STOPBITS_1;
    s_uart_handle.Init.Parity = UART_PARITY_NONE;
    s_uart_handle.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    s_uart_handle.Init.Mode = UART_MODE_TX_RX;
    HAL_UART_Init(&s_uart_handle);

    HAL_UART_Receive_IT(&s_uart_handle, &s_isr_rx_byte, 1);
}

/**
 * @brief   HAL 库单字节接收完成回调：只做"搬运"，不做拼帧
 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    uint16_t next_head;

    if (huart->Instance != PC_LINK_USART)
    {
        return;
    }

    next_head = (uint16_t)((s_ring_head + 1u) % PC_LINK_RING_CAPACITY);
    if (next_head != s_ring_tail)   /* 环形缓冲区未满才写入，满则丢弃（记为错误） */
    {
        s_ring_buf[s_ring_head] = s_isr_rx_byte;
        s_ring_head = next_head;
    }
    else
    {
        s_error_count++;
    }

    HAL_UART_Receive_IT(&s_uart_handle, &s_isr_rx_byte, 1);
}

void PC_LINK_USART_IRQHandler(void)
{
    HAL_UART_IRQHandler(&s_uart_handle);
}

/**
 * @brief   在 s_assembly_buf 中查找帧头 0xAA 0x55，丢弃其之前的无效字节（重同步），
 *          与 PC 端 FrameStreamBuffer._resync() 语义对应
 */
static void pc_link_resync(void)
{
    uint16_t i;

    if (s_assembly_len == 0u)
    {
        return;
    }

    for (i = 0; i + 1u < s_assembly_len; i++)
    {
        if (s_assembly_buf[i] == PROTOCOL_HEADER_BYTE0 && s_assembly_buf[i + 1u] == PROTOCOL_HEADER_BYTE1)
        {
            break;
        }
    }

    if (i == 0u)
    {
        return;   /* 帧头已在最前面，无需丢弃 */
    }

    if (i + 1u >= s_assembly_len)
    {
        /* 缓冲区里没有完整帧头；保留最后一个字节，防止它恰好是帧头的第一个字节 */
        uint8_t keep_last = (s_assembly_buf[s_assembly_len - 1u] == PROTOCOL_HEADER_BYTE0) ? 1u : 0u;
        s_error_count += (uint32_t)(s_assembly_len - keep_last);
        if (keep_last)
        {
            s_assembly_buf[0] = s_assembly_buf[s_assembly_len - 1u];
            s_assembly_len = 1u;
        }
        else
        {
            s_assembly_len = 0u;
        }
        return;
    }

    /* 丢弃帧头之前的 i 个脏字节 */
    {
        uint16_t remaining = (uint16_t)(s_assembly_len - i);
        uint16_t k;
        for (k = 0; k < remaining; k++)
        {
            s_assembly_buf[k] = s_assembly_buf[k + i];
        }
        s_assembly_len = remaining;
        s_error_count += i;
    }
}

void pc_link_poll(void)
{
    /* 1) 把 ISR 环形缓冲区中的字节搬到拼帧用的线性缓冲区 */
    while (s_ring_tail != s_ring_head && s_assembly_len < PC_LINK_ASSEMBLY_CAPACITY)
    {
        s_assembly_buf[s_assembly_len++] = s_ring_buf[s_ring_tail];
        s_ring_tail = (uint16_t)((s_ring_tail + 1u) % PC_LINK_RING_CAPACITY);
    }

    if (s_frame_ready)
    {
        return;   /* 上一帧尚未被取走，暂不再解析新的一帧 */
    }

    pc_link_resync();

    if (s_assembly_len < PROTOCOL_OVERHEAD_SIZE)
    {
        return;   /* 数据不足以判断长度，等待更多字节 */
    }

    {
        uint16_t declared_len = ((uint16_t)s_assembly_buf[4] << 8) | (uint16_t)s_assembly_buf[5];
        uint16_t total_len = (uint16_t)(PROTOCOL_OVERHEAD_SIZE + declared_len);

        if (total_len > PC_LINK_ASSEMBLY_CAPACITY)
        {
            /* 声明长度超出本地缓冲区容量，判定为脏数据，丢弃帧头重新同步 */
            s_assembly_buf[0] = s_assembly_buf[1];
            s_assembly_len = 1u;
            s_error_count++;
            return;
        }

        if (s_assembly_len < total_len)
        {
            return;   /* 还没收全一帧 */
        }

        {
            uint8_t device_id, command_type;
            const uint8_t *payload;
            uint16_t payload_len;
            protocol_status_t status = protocol_decode(s_assembly_buf, total_len,
                                                         &device_id, &command_type,
                                                         &payload, &payload_len);

            if (status == PROTOCOL_OK)
            {
                uint16_t copy_len = payload_len;
                if (copy_len > PC_LINK_ASSEMBLY_CAPACITY)
                {
                    copy_len = PC_LINK_ASSEMBLY_CAPACITY;   /* 理论上不会发生，防御性截断 */
                }
                if (copy_len > 0u)
                {
                    uint16_t k;
                    for (k = 0; k < copy_len; k++)
                    {
                        s_frame_payload_buf[k] = payload[k];
                    }
                }
                s_frame_device_id = device_id;
                s_frame_command_type = command_type;
                s_frame_payload_len = copy_len;
                s_frame_ready = 1u;
            }
            else
            {
                /* CRC/长度校验失败：这两个字节大概率不是真正的帧头，只是巧合出现的
                 * 0xAA 0x55，丢弃第一个字节后重新搜索，而不是整段丢弃 */
                s_error_count++;
            }

            {
                uint16_t remaining = (uint16_t)(s_assembly_len - total_len);
                uint16_t k;
                for (k = 0; k < remaining; k++)
                {
                    s_assembly_buf[k] = s_assembly_buf[k + total_len];
                }
                s_assembly_len = remaining;
            }
        }
    }
}

uint8_t pc_link_frame_ready(void)
{
    return s_frame_ready;
}

void pc_link_take_frame(uint8_t *device_id, uint8_t *command_type,
                         const uint8_t **payload, uint16_t *payload_len)
{
    *device_id = s_frame_device_id;
    *command_type = s_frame_command_type;
    *payload_len = s_frame_payload_len;
    *payload = s_frame_payload_buf;   /* 指向稳定的拷贝缓冲区，直到下一帧覆盖它之前一直有效 */
    s_frame_ready = 0u;
}

uint8_t pc_link_send_frame(uint8_t device_id, uint8_t command_type,
                            const uint8_t *payload, uint16_t payload_len)
{
    uint16_t total_len = protocol_encode(device_id, command_type, payload, payload_len,
                                          s_send_buf, PC_LINK_SEND_CAPACITY);
    if (total_len == 0u)
    {
        return 0u;
    }

    HAL_UART_Transmit(&s_uart_handle, s_send_buf, total_len, 1000u);
    return 1u;
}

uint32_t pc_link_get_error_count(void)
{
    return s_error_count;
}
