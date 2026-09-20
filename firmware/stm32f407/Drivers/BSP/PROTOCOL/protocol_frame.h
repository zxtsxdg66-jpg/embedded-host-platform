/**
 ****************************************************************************************************
 * @file        protocol_frame.h
 * @brief       通用帧协议编解码，与 docs/03_Communication/Protocol_Design.md 及 PC 端
 *              src/protocol/frame.py + encoder.py + decoder.py 严格一致，不擅自修改字段
 *              定义或字节序。
 *
 * 帧结构（全部多字节字段均为大端序）：
 *   帧头(2B, 0xAA 0x55) + 设备ID(1B) + 命令类型(1B) + 数据长度(2B) + Payload(变长) + CRC-32(4B)
 *   CRC 覆盖范围：设备ID + 命令类型 + 数据长度 + Payload（不含帧头），与 encoder.py 注释
 *   "The header sync marker is excluded from the checksum" 完全一致。
 *
 * 命令类型取值（与 src/application/manager.py 一致，权威定义处仍是该 Python 文件，
 * 本文件的取值只是同步记录，如与 PC 端代码不一致以 PC 端代码为准）：
 *   0x01 = DATA_REPORT（设备→上位机，数据上报）
 *   0x02 = COMMAND_ACK（设备→上位机，命令应答）
 *   0x10 起 = 业务命令（上位机→设备，由 PC 侧动态分配，固件不需要预先知道分配规则，
 *             只需要识别到不是 0x01/0x02 的命令类型时，视为业务命令并执行相应动作 +
 *             回复 COMMAND_ACK）
 *
 * 本模块只负责单帧的编码/解码，不负责在连续字节流中定位帧边界（粘包/半包处理）——
 * 那是 pc_link.c 的职责，与 PC 侧 protocol.decoder.decode() 只负责"给定恰好一帧字节
 * 解析出结构化数据"、frame_stream.py 的 FrameStreamBuffer 负责"从字节流中切出一帧"
 * 的职责划分完全对应。
 ****************************************************************************************************
 */
#ifndef __PROTOCOL_FRAME_H
#define __PROTOCOL_FRAME_H

#include <stdint.h>

#define PROTOCOL_HEADER_BYTE0           0xAAu
#define PROTOCOL_HEADER_BYTE1           0x55u

#define PROTOCOL_HEADER_SIZE            2u
#define PROTOCOL_DEVICE_ID_SIZE         1u
#define PROTOCOL_COMMAND_TYPE_SIZE      1u
#define PROTOCOL_LENGTH_FIELD_SIZE      2u
#define PROTOCOL_CRC_SIZE               4u

/* 帧头之后、Payload 之前的固定字节数：设备ID + 命令类型 + 数据长度 */
#define PROTOCOL_PREFIX_SIZE            (PROTOCOL_DEVICE_ID_SIZE + PROTOCOL_COMMAND_TYPE_SIZE + PROTOCOL_LENGTH_FIELD_SIZE)

/* 一帧总开销（不含 Payload）：帧头 + 前缀 + CRC */
#define PROTOCOL_OVERHEAD_SIZE          (PROTOCOL_HEADER_SIZE + PROTOCOL_PREFIX_SIZE + PROTOCOL_CRC_SIZE)

/* 与 src/application/manager.py 的 DATA_REPORT_CODE / COMMAND_ACK_CODE 一致 */
#define PROTOCOL_CMD_DATA_REPORT        0x01u
#define PROTOCOL_CMD_COMMAND_ACK        0x02u
/* 0x10 起为业务命令区间，见 docs/03_Communication/Protocol_Design.md */
#define PROTOCOL_CMD_BUSINESS_MIN       0x10u

/* 固定分配的业务命令码（0x10~0x1F 为保留区间）。
 *
 * 必须与 src/application/manager.py 的 RESERVED_COMMAND_CODES 逐个对应——这是两个
 * 独立编译的程序之间的线上契约，编译器发现不了不一致，只能靠人工核对。
 *
 * 为什么要固定：PC 端的业务命令码本来是"按首次使用顺序动态分配"的（见
 * DeviceRegistration.code_for），在固件只需回 ACK、不解释命令内容的阶段没有问题；
 * 但风扇要求 MCU 区分"开"和"关"，一个取决于本次会话谁先被发送的编号无法承载这个
 * 含义。因此凡是设备需要**解释**的命令，都必须在两边固定下来。
 * PC 端的动态分配区间已相应上移到 0x20 起，不会与本区间冲突。 */
#define PROTOCOL_CMD_FAN_ON             0x10u
#define PROTOCOL_CMD_FAN_OFF            0x11u
/* 语音告警：播报三句预合成语音之一。与 service/alarm_announcer.py 的 AlertKind 对应 */
#define PROTOCOL_CMD_ALERT_TEMPERATURE  0x12u
#define PROTOCOL_CMD_ALERT_HUMIDITY     0x13u
#define PROTOCOL_CMD_ALERT_NOISE        0x14u
/* 报警状态位图：上位机把"哪几个通道正处于报警"下发给设备，供板载 LCD 显示。
 * 与前五个命令不同，本命令的 **payload 需要被解释**——位图在 payload 的 JSON
 * 里，键名 "bits"，位序见 ui_screen.h 的 UI_ALERT_BIT_*，PC 侧对应
 * src/application/alarm_state_dispatcher.py 的 CHANNEL_BITS。
 * 阈值本身只有 PC 一份（src/service/sensor_data_processor.py），固件不重复实现，
 * 否则同一套 GB 37488-2019 论证会在 C 里出现第二份、并悄悄与 PC 端分叉。 */
#define PROTOCOL_CMD_ALERT_STATE        0x15u
/* 最近一条问答，供板载 LCD 第二页显示。payload 是六个无符号整数：
 *   kind    答案种类，见 ui_screen.h 的 UI_ANSWER_KIND_*
 *   channel 0=温度 1=湿度 2=噪声 255=与通道无关（风扇）
 *   value   数值 ×10（本链路无浮点解析，24.7 传 247）
 *   limit   阈值 ×10
 *   flags   位 0 越限 / 位 1 风扇运行 / 位 2 自动模式 / 位 3 阈值是上限
 *   source  0=PC 提问 1=移动端提问
 * PC 侧对应 src/application/answer_dispatcher.py。
 * **不下发文本**：本板字库是从 ui_screen.c 的 UI_TXT 字面量生成的子集，
 * 画不出任意中文句子；因此下发的是"哪一类答案 + 数值"，由板子用自己的模板渲染。
 * 好处不止于省字库——模型改写不会影响屏幕显示，屏幕上出现的永远是事实。 */
#define PROTOCOL_CMD_ANSWER_SHOW        0x16u

typedef enum
{
    PROTOCOL_OK = 0,
    PROTOCOL_ERR_SYNC,       /* 帧头不匹配，对应 PC 端 protocol.exceptions.FrameSyncError */
    PROTOCOL_ERR_LENGTH,     /* 声明长度与实际可用字节数不符，对应 FrameLengthError */
    PROTOCOL_ERR_CHECKSUM,   /* CRC 校验失败，对应 ChecksumError */
} protocol_status_t;

/**
 * @brief       编码一帧
 * @param       device_id       设备 ID（0-255）
 * @param       command_type    命令类型（0-255）
 * @param       payload         Payload 数据指针，payload_len 为 0 时可传 NULL
 * @param       payload_len     Payload 长度（字节），最大 0xFFFF
 * @param       out             输出缓冲区
 * @param       out_capacity    输出缓冲区容量（字节），必须 >= PROTOCOL_OVERHEAD_SIZE + payload_len
 * @retval      实际写入 out 的字节数；若 out_capacity 不足则返回 0（不写入任何数据）
 */
uint16_t protocol_encode(uint8_t device_id, uint8_t command_type,
                          const uint8_t *payload, uint16_t payload_len,
                          uint8_t *out, uint16_t out_capacity);

/**
 * @brief       解码恰好一帧的字节（调用方需先用 pc_link.c 的拼帧逻辑切出完整的一帧，
 *              本函数不处理粘包/半包）
 * @param       frame           一帧完整字节（从帧头 0xAA 0x55 开始，到 CRC 结束）
 * @param       frame_len       frame 的长度
 * @param       device_id       [出参] 解出的设备 ID
 * @param       command_type    [出参] 解出的命令类型
 * @param       payload         [出参] 指向 frame 内部 Payload 起始位置（不做拷贝）
 * @param       payload_len     [出参] Payload 长度
 * @retval      PROTOCOL_OK 或对应的错误码
 */
protocol_status_t protocol_decode(const uint8_t *frame, uint16_t frame_len,
                                   uint8_t *device_id, uint8_t *command_type,
                                   const uint8_t **payload, uint16_t *payload_len);

/**
 * @brief       从 JSON payload 中取出一个无符号整数字段
 * @param       payload     payload 起始地址（UTF-8 JSON，非零结尾）
 * @param       payload_len payload 长度
 * @param       key         字段名，不含引号
 * @param       out_value   [出参] 解析出的数值
 * @retval      1=找到并解析成功；0=未找到或格式不符
 *
 * @note        这是一个**极小的键值扫描**，不是 JSON 解析器：找到 "key" 之后跳过冒号
 *              与空白，读连续的十进制数字。之所以不引入 JSON 解析器，是因为本链路上
 *              固件唯一需要读的字段就是这一个整数（见 PROTOCOL_CMD_ALERT_STATE），
 *              为它背一个解析器进 Flash 不划算；而之所以 payload 仍然是 JSON、没有
 *              为它单开一种二进制格式，是因为"命令 payload 一律是 JSON"是这条链路
 *              已经成文的约定（见 src/application/manager.py 模块注释），为一条命令
 *              破例会让协议文档多出一条特例。
 *              局限性也如实说明：不理解嵌套对象、转义与字符串值，键名出现在字符串
 *              值里会误匹配。当前 payload 形如 {"bits": 5}，不存在这些情况。
 */
uint8_t protocol_payload_get_uint(const uint8_t *payload, uint16_t payload_len,
                                   const char *key, uint32_t *out_value);

#endif
