/**
 ****************************************************************************************************
 * @file        ui_screen.h
 * @brief       板载 2.8 寸 TFT LCD（ATK-MD0280）本地仪表盘。
 *
 * 职责边界：本模块**只负责画面与触摸**，不做任何业务判定。
 *   - 三个传感器数值由 main.c 在每个采集周期结束时喂进来；
 *   - 报警状态由上位机通过 PROTOCOL_CMD_ALERT_STATE 下发（阈值只有 PC 一份，
 *     见 src/service/data_processor.py），固件不重复实现一套阈值；
 *   - 触摸只上报事件（ui_screen_poll 的返回值），由 main.c 决定做什么。
 * 这样 LCD 换一块、按钮换一个动作，都不牵动固件其它部分。
 *
 * 为什么屏幕上显示的都是固件**确实知道**的状态：数值来自本机采集，风扇状态来自
 * fan_is_running()（是本机执行的结果），播报状态来自 audio_alert_is_playing()，
 * 链路状态来自"距上一帧 PC 数据多久"，报警状态由 PC 显式下发。没有任何一项是
 * 屏幕自己推断出来的——推断出来的状态一旦与 PC 端不一致，演示时就是事故。
 *
 * 布局（320x240 横屏）：
 *   y 0..25    标题栏：站点名 + 链路状态 + 「数据」「问答」两个页签
 *   y 26..193  正文区，按当前页签切换：
 *                第一页  三行数据行，每行 56 高：标签 / 数值 / 单位 / 状态
 *                第二页  最近一条问答：种类 + 数值 + 单位 + 判定 + 阈值 + 来源
 *   y 194..239 底栏：风扇状态 + 「语音自检」按钮（两页都在）
 *
 * 为什么是分页而不是下拉滚动：这块屏是**电阻屏**，单点、需按压、没有惯性滚动，
 * 拖动恰恰是最吃触摸校准误差的操作，而校准误差在本项目里已经是踩过的坑
 * （见 ui_screen_poll 里 KEY0 那段）。离散页签按偏几个像素照样命中；滚动还要
 * 维护偏移量与局部重绘，代价和风险都更高。
 *
 * 字体：ASCII 直接用厂商 lcdfont.h 里已经编译进来的点阵（24x24 的 asc2_2412），
 * 数值再按整数 2 倍放大成 24x48 以便一两米外看清；汉字用 hzfont.c 里的子集点阵，
 * 由 scripts/hz_font_to_c.py 从本目录所有 UI_TXT("...") 字面量自动提取生成。
 *
 * 刷新策略：静态框架只在 ui_screen_init() 里画一次，之后每个采集周期只重绘发生
 * 变化的那几个字段（见 ui_screen.c 里的 s_shadow_* 影子变量）。绝不整屏刷新——
 * 320x240x2 = 150KB 的 FSMC 写入会挤占采集周期里留给 Modbus 应答的等待窗口，而
 * "Modbus 应答成功率"是论文第 9 章的硬指标，显示不能去动它。
 ****************************************************************************************************
 */
#ifndef __UI_SCREEN_H
#define __UI_SCREEN_H

#include <stdint.h>
#include "./BSP/SENSOR_DATA/sensor_data.h"

/**
 * @brief   屏幕文案标记宏。
 *
 * 展开后就是字符串本身，不产生任何代码；它的唯一作用是让
 * scripts/hz_font_to_c.py 能把"要显示的文字"和"中文注释"区分开——扫描器只认
 * UI_TXT(...) 里的字面量。凡是会被画到屏幕上的中文，都必须用它包起来，否则
 * 重新生成字库时那些字不会被收进子集，屏幕上会留空白。
 */
#define UI_TXT(s)                   (s)

/* 汉字点阵规格。改这里必须同步改 scripts/hz_font_to_c.py 的 FONT_SIZE。 */
#define HZ_FONT_SIZE                24u
#define HZ_FONT_BYTES_PER_ROW       ((HZ_FONT_SIZE + 7u) / 8u)
#define HZ_FONT_BYTES               (HZ_FONT_BYTES_PER_ROW * HZ_FONT_SIZE)

/**
 * @brief   一个汉字的点阵。行优先，每行 3 字节，最高位对应最左像素。
 * @note    与厂商 ASCII 字库的列优先布局不同——那种布局是为 lcd_show_char()
 *          逐点绘制的循环准备的，而本模块按整行写 GRAM（快得多），要的是行优先。
 */
typedef struct
{
    uint16_t code;                  /* Unicode 码点（本项目用到的全部落在 BMP 内） */
    uint8_t  dots[HZ_FONT_BYTES];
} hz_glyph_t;

extern const hz_glyph_t g_hz_glyphs[];   /* 按 code 升序排列，便于二分查找 */
extern const uint16_t g_hz_glyph_count;

/**
 * @brief   报警状态位图，与 PROTOCOL_CMD_ALERT_STATE 的 payload 第一个字节一致，
 *          也与 PC 端 src/application/alarm_state_dispatcher.py 的位序一致。
 */
#define UI_ALERT_BIT_TEMPERATURE    0x01u
#define UI_ALERT_BIT_HUMIDITY       0x02u
#define UI_ALERT_BIT_NOISE          0x04u

/**
 * @brief   第二页显示的答案种类。数值与 PC 端
 *          src/application/answer_dispatcher.py 的 AnswerKind 一一对应，
 *          是**线上契约**，不得重新编号。
 */
#define UI_ANSWER_KIND_NONE         0u      /* 还没收到过任何一条 */
#define UI_ANSWER_KIND_CURRENT      1u
#define UI_ANSWER_KIND_MAXIMUM      2u
#define UI_ANSWER_KIND_MINIMUM      3u
#define UI_ANSWER_KIND_AVERAGE      4u
#define UI_ANSWER_KIND_ALARM        5u
#define UI_ANSWER_KIND_THRESHOLD    6u
#define UI_ANSWER_KIND_FAN          7u

#define UI_ANSWER_CHANNEL_NONE      255u    /* 与通道无关（风扇） */

/* 答案标志位，与 answer_dispatcher.py 的 FLAG_* 一致 */
#define UI_ANSWER_FLAG_TRIGGERED    0x01u
#define UI_ANSWER_FLAG_FAN_RUNNING  0x02u
#define UI_ANSWER_FLAG_FAN_AUTO     0x04u
#define UI_ANSWER_FLAG_LIMIT_MAX    0x08u

#define UI_ANSWER_SOURCE_LOCAL      0u      /* PC 上提的问 */
#define UI_ANSWER_SOURCE_REMOTE     1u      /* 手机上提的问 */

/**
 * @brief   触摸事件
 */
typedef enum
{
    UI_EVENT_NONE = 0,      /* 本次轮询没有产生事件 */
    UI_EVENT_SELF_TEST,     /* 「语音自检」按钮被按下（按下沿，非持续按住） */
} ui_event_t;

/**
 * @brief       初始化 LCD 与触摸屏，并绘制静态框架
 * @retval      0=成功；1=LCD 未检出（未插屏或接触不良），此时后续所有绘制调用
 *              都会直接返回，不影响采集与上报
 * @note        必须在 delay_init() 之后调用。首次上电若 24C02 中没有触摸校准
 *              参数，厂商的 tp_init() 会进入**阻塞式**五点校准界面等待用户点击；
 *              这是一次性的，校准值存入 24C02 后掉电不丢。
 */
uint8_t ui_screen_init(void);

/**
 * @brief       更新三个传感器数值
 * @param       data    本周期采集结果；valid=0 的通道显示 "--"
 * @note        只重绘与上次不同的字段。
 */
void ui_screen_set_values(const sensor_data_t *data);

/**
 * @brief       更新报警状态位图（来自上位机）
 * @param       alert_bits  UI_ALERT_BIT_* 的按位或
 */
void ui_screen_set_alerts(uint8_t alert_bits);

/**
 * @brief       更新底栏的风扇/播报状态
 * @param       fan_running     风扇是否在转
 * @param       audio_playing   是否正在播报语音
 */
void ui_screen_set_actuators(uint8_t fan_running, uint8_t audio_playing);

/**
 * @brief       更新标题栏的链路状态
 * @param       linked  是否与上位机保持通信
 */
void ui_screen_set_link(uint8_t linked);

/**
 * @brief       更新第二页显示的"最近一条问答"
 * @param       kind        UI_ANSWER_KIND_*，NONE 表示清空
 * @param       channel     0=温度 1=湿度 2=噪声，UI_ANSWER_CHANNEL_NONE=与通道无关
 * @param       value_x10   数值 ×10（本链路没有浮点，24.7 传 247）
 * @param       limit_x10   阈值 ×10
 * @param       flags       UI_ANSWER_FLAG_* 的按位或
 * @param       source      UI_ANSWER_SOURCE_*
 *
 * @note        **下发的不是文本，是"哪一类答案 + 数值"。** 本板字库是从本目录
 *              UI_TXT 字面量生成的子集（完整 GBK 需外挂 SPI Flash，其总线占
 *              JTAG 引脚），画不出任意中文句子；所以由 PC 告诉板子是哪一类答案，
 *              板子用自己的模板渲染。附带的好处是：**上位机那边模型改写措辞
 *              不会影响屏幕**，屏幕上出现的永远是事实，这与整套问答"模型管措辞、
 *              系统管数字"的分工是同一条原则。
 *
 *              当前不在第二页时只记录不重绘，切页时一并画出。
 */
void ui_screen_set_answer(uint8_t kind, uint8_t channel, uint16_t value_x10,
                          uint16_t limit_x10, uint8_t flags, uint8_t source);

/**
 * @brief       扫描触摸屏，返回本次产生的事件
 * @retval      ui_event_t
 * @note        每个主循环节拍调用一次即可；内部做了按下沿检测，按住不放只触发一次。
 */
ui_event_t ui_screen_poll(void);

#endif /* __UI_SCREEN_H */
