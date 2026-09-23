/**
 ****************************************************************************************************
 * @file        ui_screen.c
 * @brief       板载 2.8 寸 TFT LCD 仪表盘的绘制与触摸处理，接口说明见 ui_screen.h。
 ****************************************************************************************************
 */

#include <stdio.h>
#include <string.h>

#include "./BSP/UI_SCREEN/ui_screen.h"
#include "./BSP/LCD/lcd.h"
#include "./BSP/TOUCH/touch.h"
#include "./BSP/DEBUG_LOG/debug_log.h"

/* 厂商 ASCII 点阵在 lcdfont.h 里是**定义**（file-scope const，具有外部链接），
 * 而 lcd.c 已经包含了那个头文件。这里若再包含一次就会产生重复定义，所以只做
 * extern 声明，借用 lcd.o 里已有的那一份，不额外占 Flash。
 * 布局：12 宽 x 24 高，列优先，每列 3 字节。 */
extern const unsigned char asc2_2412[95][36];

/* 板载 KEY0。按下它可随时强制重新做触摸校准，见 ui_screen_poll()。
 * PE4 在本项目中空闲（PE0/PE1 给 AHT20，PE5/PE6 给风扇，PE7~PE15 给 FSMC）。 */
#define UI_KEY0_GPIO_PORT       GPIOE
#define UI_KEY0_GPIO_PIN        GPIO_PIN_4
#define UI_KEY0_GPIO_CLK_ENABLE()   do{ __HAL_RCC_GPIOE_CLK_ENABLE(); }while(0)

/* ---------------------------------------------------------------------------
 * 布局常量。全部集中在这里，改版式不必翻遍绘制代码。
 * ------------------------------------------------------------------------- */
#define UI_SCREEN_W             320u
#define UI_SCREEN_H             240u

#define UI_TITLE_H              26u          /* 标题栏高度 */
#define UI_ROW_TOP              26u          /* 第一行数据行的顶边 */
#define UI_ROW_H                56u          /* 每行数据行高度 */
#define UI_ROW_COUNT            3u
#define UI_BOTTOM_TOP           194u         /* 底栏顶边 = UI_ROW_TOP + 3 * UI_ROW_H */

#define UI_LABEL_X              8u           /* 行内：中文标签 */
#define UI_LABEL_W              48u
#define UI_VALUE_X              64u          /* 行内：2 倍放大的数值 */
#define UI_VALUE_W              120u         /* 5 个字符 x 24 像素 */
#define UI_UNIT_X               190u         /* 行内：单位 */
#define UI_UNIT_W               36u
#define UI_STATUS_X             246u         /* 行内：正常/报警/无效 */
#define UI_STATUS_W             48u

#define UI_LINK_X               240u         /* 标题栏右侧的链路状态 */
#define UI_LINK_W               72u

/* 页签。放在标题栏右侧而不是底栏，是因为底栏已经被风扇状态与「语音自检」占满，
 * 而标题栏右半边原本只有链路状态。两页共用底栏，语音自检在哪一页都按得到。 */
#define UI_TAB_COUNT            2u
#define UI_TAB_W                68u
#define UI_TAB_H                24u
#define UI_TAB_Y0               1u
#define UI_TAB_Y1               (UI_TAB_Y0 + UI_TAB_H - 1u)
#define UI_TAB0_X0              176u
#define UI_TAB1_X0              246u
#define UI_TAB_TEXT_DY          1u

/* 第二页正文区（y 26..193，与第一页共用同一块矩形） */
#define UI_BODY_TOP             UI_ROW_TOP
#define UI_BODY_BOTTOM          (UI_BOTTOM_TOP - 2u)
#define UI_ANS_TITLE_Y          34u          /* 「最近提问」+ 来源 */
#define UI_ANS_KIND_Y           74u          /* 通道 + 种类，例如「噪声 最高」 */
#define UI_ANS_VALUE_Y          108u         /* 2 倍放大的数值 */
#define UI_ANS_FOOT_Y           162u         /* 判定与阈值 */
#define UI_ANS_X                12u

#define UI_FAN_LABEL_X          8u
#define UI_FAN_STATE_X          64u
#define UI_AUDIO_STATE_X        124u
#define UI_ACT_TEXT_Y           204u         /* 底栏文字基线（顶边） */

#define UI_BTN_X0               210u         /* 「语音自检」按钮 */
#define UI_BTN_Y0               198u
#define UI_BTN_X1               316u
#define UI_BTN_Y1               236u
#define UI_BTN_TEXT_X           215u
#define UI_BTN_TEXT_Y           205u

/* ---------------------------------------------------------------------------
 * 配色。浅色底、深色字——文档里要插屏幕照片，浅色底翻拍和印刷都更清楚。
 * ------------------------------------------------------------------------- */
#define UI_COLOR_BG             WHITE
#define UI_COLOR_TITLE_BG       DARKBLUE
#define UI_COLOR_TITLE_FG       WHITE
#define UI_COLOR_LABEL          BLACK
#define UI_COLOR_VALUE          BLACK
#define UI_COLOR_VALUE_ALARM    RED
#define UI_COLOR_OK             BLUE
#define UI_COLOR_ALARM          RED
#define UI_COLOR_MUTED          GRAY
#define UI_COLOR_LINE           LGRAY
#define UI_COLOR_BTN_BG         LIGHTBLUE
#define UI_COLOR_BTN_BG_DOWN    BLUE
#define UI_COLOR_BTN_FG         BLACK

#define UI_VALUE_TEXT_LEN       6u           /* "100.0" + 结束符 */

/**
 * @brief   一行数据行的静态配置
 */
typedef struct
{
    const char *label;      /* 中文标签，两个字 */
    const char *unit;       /* 单位，ASCII 或 ASCII+度符号 */
    uint8_t     alert_bit;  /* 该通道在报警位图中的位 */
} ui_row_config_t;

static const ui_row_config_t s_rows[UI_ROW_COUNT] =
{
    { UI_TXT("温度"), UI_TXT("°C"),  UI_ALERT_BIT_TEMPERATURE },
    { UI_TXT("湿度"), UI_TXT("%RH"), UI_ALERT_BIT_HUMIDITY    },
    { UI_TXT("噪声"), UI_TXT("dB"),  UI_ALERT_BIT_NOISE       },
};

/* ---------------------------------------------------------------------------
 * 影子状态。每个字段记住上一次画上去的内容，只有变化时才重绘——这是"不整屏刷新"
 * 策略的具体落实，见 ui_screen.h 的刷新策略说明。
 * ------------------------------------------------------------------------- */
static uint8_t s_ready = 0u;                                    /* LCD 是否可用 */
static char    s_shadow_value[UI_ROW_COUNT][UI_VALUE_TEXT_LEN];
static uint8_t s_shadow_status[UI_ROW_COUNT];                   /* 0=正常 1=报警 2=无效，0xFF=未画过 */
static uint8_t s_shadow_alerts = 0u;
static uint8_t s_shadow_fan = 0xFFu;
static uint8_t s_shadow_audio = 0xFFu;
static uint8_t s_shadow_link = 0xFFu;
static uint8_t s_touch_was_down = 0u;
static uint8_t s_btn_is_down = 0u;

/* 当前页签，以及第二页要显示的那条问答。答案整条存下来而不是存渲染好的字符串：
 * 切页时要重画，而重新格式化比留着一份可能过期的文本更不容易出错。 */
static uint8_t  s_page = 0u;
static uint8_t  s_answer_kind = UI_ANSWER_KIND_NONE;
static uint8_t  s_answer_channel = UI_ANSWER_CHANNEL_NONE;
static uint16_t s_answer_value = 0u;
static uint16_t s_answer_limit = 0u;
static uint8_t  s_answer_flags = 0u;
static uint8_t  s_answer_source = UI_ANSWER_SOURCE_LOCAL;

/* 状态码，供 s_shadow_status 使用 */
#define UI_STATUS_OK        0u
#define UI_STATUS_ALARM     1u
#define UI_STATUS_INVALID   2u
#define UI_STATUS_UNDRAWN   0xFFu

/**
 * @brief       二分查找一个码点对应的汉字点阵
 * @param       code    Unicode 码点
 * @retval      点阵指针；找不到返回 NULL（该字未被收进子集，通常意味着改了文案
 *              却忘了重新运行 scripts/hz_font_to_c.py）
 */
static const uint8_t *hz_lookup(uint16_t code)
{
    uint16_t low = 0u;
    uint16_t high = g_hz_glyph_count;

    while (low < high)
    {
        uint16_t mid = (uint16_t)(low + ((high - low) / 2u));

        if (g_hz_glyphs[mid].code == code)
        {
            return g_hz_glyphs[mid].dots;
        }
        else if (g_hz_glyphs[mid].code < code)
        {
            low = (uint16_t)(mid + 1u);
        }
        else
        {
            high = mid;
        }
    }

    return 0;
}

/**
 * @brief       画一个 24x24 汉字（不透明，连背景一起写）
 * @note        按整行写 GRAM：每行只调用一次 lcd_set_cursor()，其余就是连续的
 *              FSMC 写入。比 lcd_show_char() 的逐点 lcd_draw_point() 快一个量级，
 *              而且因为背景像素也一起写了，不需要先清一块区域，没有闪烁。
 */
static void draw_hz(uint16_t x, uint16_t y, const uint8_t *dots, uint16_t fg, uint16_t bg)
{
    uint16_t row;
    uint16_t col;

    for (row = 0u; row < HZ_FONT_SIZE; row++)
    {
        const uint8_t *line = &dots[row * HZ_FONT_BYTES_PER_ROW];

        lcd_set_cursor(x, (uint16_t)(y + row));
        lcd_write_ram_prepare();

        for (col = 0u; col < HZ_FONT_SIZE; col++)
        {
            uint8_t bit = (uint8_t)(line[col >> 3] & (uint8_t)(0x80u >> (col & 7u)));
            LCD->LCD_RAM = bit ? fg : bg;
        }
    }
}

/**
 * @brief       画一个 ASCII 字符，可整数倍放大
 * @param       scale   放大倍数（1 = 12x24，2 = 24x48）
 * @note        整数倍放大是纯粹的像素复制，不需要额外的大号字库，也就不占 Flash。
 *              数值用 2 倍显示，是为了在一两米外的演示距离上能看清。
 */
static void draw_ascii(uint16_t x, uint16_t y, char chr, uint8_t scale, uint16_t fg, uint16_t bg)
{
    uint16_t row;
    uint16_t col;
    uint8_t index;

    if ((chr < ' ') || (chr > '~'))
    {
        chr = ' ';
    }
    index = (uint8_t)(chr - ' ');

    for (row = 0u; row < (uint16_t)(24u * scale); row++)
    {
        uint16_t src_row = (uint16_t)(row / scale);

        lcd_set_cursor(x, (uint16_t)(y + row));
        lcd_write_ram_prepare();

        for (col = 0u; col < (uint16_t)(12u * scale); col++)
        {
            uint16_t src_col = (uint16_t)(col / scale);
            /* 厂商字库是列优先：每列 3 字节，共 12 列 */
            uint8_t bit = (uint8_t)(asc2_2412[index][(src_col * 3u) + (src_row >> 3)]
                                    & (uint8_t)(0x80u >> (src_row & 7u)));
            LCD->LCD_RAM = bit ? fg : bg;
        }
    }
}

/**
 * @brief       画一段 UTF-8 文本，并把字段剩余宽度用背景色补齐
 * @param       field_w 字段总宽度（像素）。文本画完后剩下的部分填背景色，这样
 *                      新文本比旧文本短时不会留下上一次的残影，省掉一次单独的
 *                      清空操作（清空再画会闪）。
 * @param       scale   ASCII 的放大倍数；汉字始终 1 倍（子集里只有 24x24 一种）
 * @note        只处理 1 字节（ASCII）与 2/3 字节（BMP）的 UTF-8 序列。本项目
 *              屏幕上不会出现 4 字节序列（那是补充平面的表情符号）。
 */
static void draw_text_field(uint16_t x, uint16_t y, uint16_t field_w,
                            const char *text, uint8_t scale, uint16_t fg, uint16_t bg)
{
    uint16_t cursor = x;
    const uint16_t limit = (uint16_t)(x + field_w);
    const unsigned char *p = (const unsigned char *)text;

    while (*p != 0u)
    {
        uint16_t code;
        uint16_t advance;

        if (*p < 0x80u)
        {
            code = *p;
            p += 1;
            advance = (uint16_t)(12u * scale);
        }
        else if ((*p & 0xE0u) == 0xC0u)
        {
            code = (uint16_t)(((uint16_t)(*p & 0x1Fu) << 6) | (uint16_t)(p[1] & 0x3Fu));
            p += 2;
            advance = HZ_FONT_SIZE;
        }
        else if ((*p & 0xF0u) == 0xE0u)
        {
            code = (uint16_t)(((uint16_t)(*p & 0x0Fu) << 12)
                              | ((uint16_t)(p[1] & 0x3Fu) << 6)
                              | (uint16_t)(p[2] & 0x3Fu));
            p += 3;
            advance = HZ_FONT_SIZE;
        }
        else
        {
            break;   /* 非预期的编码，停止绘制而不是画出乱码 */
        }

        if ((uint16_t)(cursor + advance) > limit)
        {
            break;   /* 放不下了，宁可截断也不越界画到隔壁字段上 */
        }

        if (code < 0x80u)
        {
            draw_ascii(cursor, y, (char)code, scale, fg, bg);
        }
        else
        {
            const uint8_t *dots = hz_lookup(code);

            if (dots != 0)
            {
                draw_hz(cursor, y, dots, fg, bg);
            }
            else
            {
                /* 字库子集里没有这个字。画成背景色空格而不是乱码方块，
                 * 屏幕上表现为缺字，提示需要重新生成字库。 */
                lcd_fill(cursor, y, (uint16_t)(cursor + advance - 1u),
                         (uint16_t)(y + HZ_FONT_SIZE - 1u), bg);
            }
        }

        cursor = (uint16_t)(cursor + advance);
    }

    if (cursor < limit)
    {
        uint16_t height = (uint16_t)((scale > 1u) ? (24u * scale) : HZ_FONT_SIZE);
        lcd_fill(cursor, y, (uint16_t)(limit - 1u), (uint16_t)(y + height - 1u), bg);
    }
}

/**
 * @brief       把一个通道的读数格式化成右对齐的 5 字符文本
 * @note        右对齐是为了让小数点位置固定——数值在 9.9/10.0 之间跳动时，
 *              左对齐会让整串数字左右横跳，读数很难看清。
 */
static void format_value(char *out, size_t out_size, const sensor_reading_t *reading)
{
    if (reading->valid != 0u)
    {
        (void)snprintf(out, out_size, "%5.1f", (double)reading->value);
    }
    else
    {
        (void)snprintf(out, out_size, "%s", "   --");
    }
}

static uint16_t row_top(uint8_t index)
{
    return (uint16_t)(UI_ROW_TOP + ((uint16_t)index * UI_ROW_H));
}

/**
 * @brief       绘制静态框架：标题栏、行分隔线、标签、单位、底栏、按钮
 * @note        只在初始化时调用一次。
 */
static void ui_screen_invalidate(void);

/**
 * @brief       画一个页签
 * @param       index   0=数据 1=问答
 * @param       active  是否为当前页
 */
static void draw_tab(uint8_t index, uint8_t active)
{
    uint16_t x0 = (index == 0u) ? UI_TAB0_X0 : UI_TAB1_X0;
    uint16_t x1 = (uint16_t)(x0 + UI_TAB_W - 1u);
    uint16_t bg = active ? UI_COLOR_BG : UI_COLOR_TITLE_BG;
    uint16_t fg = active ? UI_COLOR_LABEL : UI_COLOR_TITLE_FG;

    lcd_fill(x0, UI_TAB_Y0, x1, UI_TAB_Y1, bg);
    draw_text_field((uint16_t)(x0 + 10u), (uint16_t)(UI_TAB_Y0 + UI_TAB_TEXT_DY),
                    48u, (index == 0u) ? UI_TXT("数据") : UI_TXT("问答"), 1u, fg, bg);
}

/**
 * @brief       把正文区擦成背景色
 * @note        只擦 y 26..192 这一块，不动标题栏与底栏——两页共用它们，
 *              整屏清除会让链路状态、风扇状态、页签一起消失再重画，
 *              而 320x240x2 的 FSMC 写入会挤占本周期留给 Modbus 应答的窗口。
 */
static void clear_body(void)
{
    lcd_fill(0u, UI_BODY_TOP, (uint16_t)(UI_SCREEN_W - 1u), UI_BODY_BOTTOM,
             UI_COLOR_BG);
}

/**
 * @brief       画第一页的静态部分（三行的标签、单位、分隔线）
 */
static void draw_page_data(void)
{
    uint8_t i;

    for (i = 0u; i < UI_ROW_COUNT; i++)
    {
        uint16_t top = row_top(i);

        draw_text_field(UI_LABEL_X, (uint16_t)(top + 16u), UI_LABEL_W,
                        s_rows[i].label, 1u, UI_COLOR_LABEL, UI_COLOR_BG);
        draw_text_field(UI_UNIT_X, (uint16_t)(top + 16u), UI_UNIT_W,
                        s_rows[i].unit, 1u, UI_COLOR_LABEL, UI_COLOR_BG);

        if (i + 1u < UI_ROW_COUNT)
        {
            lcd_draw_hline(0u, (uint16_t)(top + UI_ROW_H - 1u), UI_SCREEN_W,
                           UI_COLOR_LINE);
        }
    }
}

/**
 * @brief       把 ×10 的定点数格式化成 "24.7"
 * @note        链路上没有浮点：PC 端乘 10 发过来，这里除回去。一位小数与
 *              第一页的数值、PC 界面的指标卡一致，三处读起来才是同一个数。
 */
static void format_fixed(char *out, size_t out_size, uint16_t value_x10)
{
    (void)snprintf(out, out_size, "%u.%u",
                   (unsigned int)(value_x10 / 10u),
                   (unsigned int)(value_x10 % 10u));
}

/**
 * @brief       第二页：通道名，没有则返回空串
 */
static const char *answer_channel_label(void)
{
    if (s_answer_channel < UI_ROW_COUNT)
    {
        return s_rows[s_answer_channel].label;
    }
    return "";
}

static const char *answer_channel_unit(void)
{
    if (s_answer_channel < UI_ROW_COUNT)
    {
        return s_rows[s_answer_channel].unit;
    }
    return "";
}

/**
 * @brief       第二页：这条答案是哪一类
 */
static const char *answer_kind_label(void)
{
    switch (s_answer_kind)
    {
        case UI_ANSWER_KIND_CURRENT:   return UI_TXT("当前");
        case UI_ANSWER_KIND_MAXIMUM:   return UI_TXT("最高");
        case UI_ANSWER_KIND_MINIMUM:   return UI_TXT("最低");
        case UI_ANSWER_KIND_AVERAGE:   return UI_TXT("平均");
        case UI_ANSWER_KIND_ALARM:     return UI_TXT("是否越限");
        case UI_ANSWER_KIND_THRESHOLD: return UI_TXT("阈值");
        case UI_ANSWER_KIND_FAN:       return UI_TXT("风扇");
        default:                       return "";
    }
}

/**
 * @brief       画第二页
 * @note        没收到过任何一条时显示「尚无提问」，而不是留一片空白——
 *              空白无法与"屏幕坏了"区分开。
 */
static void draw_page_answer(void)
{
    /* 比第一页的 UI_VALUE_TEXT_LEN 宽一点：定点值理论上可到 65535，写成
     * "6553.5" 是 6 个字符。实际数值远小于此，但缓冲按字段的取值范围定，
     * 而不是按"目前碰巧不会那么大"定。 */
    char text[10];

    draw_text_field(UI_ANS_X, UI_ANS_TITLE_Y, 120u, UI_TXT("最近提问"), 1u,
                    UI_COLOR_LABEL, UI_COLOR_BG);

    if (s_answer_kind == UI_ANSWER_KIND_NONE)
    {
        draw_text_field(UI_ANS_X, UI_ANS_KIND_Y, 200u, UI_TXT("尚无提问"), 1u,
                        UI_COLOR_MUTED, UI_COLOR_BG);
        return;
    }

    /* 来源：这块屏是车站里的公共面，不是谁的私人会话，两端的提问都显示；
     * 但显示出是谁问的，与 PC 活动日志记"移动端下发"是同一个理由。 */
    draw_text_field(180u, UI_ANS_TITLE_Y, 120u,
                    (s_answer_source == UI_ANSWER_SOURCE_REMOTE)
                        ? UI_TXT("来自手机") : UI_TXT("来自本机"),
                    1u, UI_COLOR_MUTED, UI_COLOR_BG);

    if (s_answer_kind == UI_ANSWER_KIND_FAN)
    {
        draw_text_field(UI_ANS_X, UI_ANS_KIND_Y, 120u, UI_TXT("风扇"), 1u,
                        UI_COLOR_LABEL, UI_COLOR_BG);
        draw_text_field(UI_ANS_X, UI_ANS_VALUE_Y, 200u,
                        ((s_answer_flags & UI_ANSWER_FLAG_FAN_RUNNING) != 0u)
                            ? UI_TXT("运行") : UI_TXT("停止"),
                        1u, UI_COLOR_VALUE, UI_COLOR_BG);
        draw_text_field(UI_ANS_X, UI_ANS_FOOT_Y, 200u,
                        ((s_answer_flags & UI_ANSWER_FLAG_FAN_AUTO) != 0u)
                            ? UI_TXT("自动") : UI_TXT("手动"),
                        1u, UI_COLOR_MUTED, UI_COLOR_BG);
        return;
    }

    /* 「噪声 最高」 */
    draw_text_field(UI_ANS_X, UI_ANS_KIND_Y, 60u, answer_channel_label(), 1u,
                    UI_COLOR_LABEL, UI_COLOR_BG);
    draw_text_field(76u, UI_ANS_KIND_Y, 120u, answer_kind_label(), 1u,
                    UI_COLOR_LABEL, UI_COLOR_BG);

    /* 数值。阈值类答案要显示的就是阈值本身，其余显示 value。 */
    format_fixed(text, sizeof(text),
                 (s_answer_kind == UI_ANSWER_KIND_THRESHOLD)
                     ? s_answer_limit : s_answer_value);
    draw_text_field(UI_ANS_X, UI_ANS_VALUE_Y, 150u, text, 2u,
                    ((s_answer_flags & UI_ANSWER_FLAG_TRIGGERED) != 0u)
                        ? UI_COLOR_VALUE_ALARM : UI_COLOR_VALUE,
                    UI_COLOR_BG);
    draw_text_field(170u, (uint16_t)(UI_ANS_VALUE_Y + 24u), 60u,
                    answer_channel_unit(), 1u, UI_COLOR_LABEL, UI_COLOR_BG);

    if (s_answer_kind == UI_ANSWER_KIND_THRESHOLD)
    {
        return;
    }

    /* 判定 + 阈值。阈值一并画出来，是因为"32.0 dB"单独摆着说明不了什么，
     * 而"未越限 / 阈值 80.0"一眼就能读懂。 */
    draw_text_field(UI_ANS_X, UI_ANS_FOOT_Y, 72u,
                    ((s_answer_flags & UI_ANSWER_FLAG_TRIGGERED) != 0u)
                        ? UI_TXT("已越限") : UI_TXT("正常"),
                    1u,
                    ((s_answer_flags & UI_ANSWER_FLAG_TRIGGERED) != 0u)
                        ? UI_COLOR_ALARM : UI_COLOR_OK,
                    UI_COLOR_BG);

    if (s_answer_limit != 0u)
    {
        draw_text_field(100u, UI_ANS_FOOT_Y, 48u, UI_TXT("阈值"), 1u,
                        UI_COLOR_MUTED, UI_COLOR_BG);
        format_fixed(text, sizeof(text), s_answer_limit);
        draw_text_field(152u, UI_ANS_FOOT_Y, 120u, text, 1u,
                        UI_COLOR_MUTED, UI_COLOR_BG);
    }
}

/**
 * @brief       重画正文区（按当前页签）
 */
static void draw_body(void)
{
    clear_body();
    if (s_page == 0u)
    {
        draw_page_data();
    }
    else
    {
        draw_page_answer();
    }
}

static void draw_static_frame(void)
{
    lcd_clear(UI_COLOR_BG);

    /* 标题栏 */
    lcd_fill(0u, 0u, (uint16_t)(UI_SCREEN_W - 1u), (uint16_t)(UI_TITLE_H - 1u), UI_COLOR_TITLE_BG);
    draw_text_field(6u, 1u, 168u, UI_TXT("地铁站环境监测"), 1u,
                    UI_COLOR_TITLE_FG, UI_COLOR_TITLE_BG);

    draw_tab(0u, (uint8_t)(s_page == 0u));
    draw_tab(1u, (uint8_t)(s_page == 1u));

    draw_body();

    /* 底栏 */
    lcd_draw_hline(0u, (uint16_t)(UI_BOTTOM_TOP - 1u), UI_SCREEN_W, UI_COLOR_LINE);
    draw_text_field(UI_FAN_LABEL_X, UI_ACT_TEXT_Y, UI_LABEL_W, UI_TXT("风扇"), 1u,
                    UI_COLOR_LABEL, UI_COLOR_BG);

    lcd_fill(UI_BTN_X0, UI_BTN_Y0, UI_BTN_X1, UI_BTN_Y1, UI_COLOR_BTN_BG);
    draw_text_field(UI_BTN_TEXT_X, UI_BTN_TEXT_Y, 96u, UI_TXT("语音自检"), 1u,
                    UI_COLOR_BTN_FG, UI_COLOR_BTN_BG);
}

uint8_t ui_screen_init(void)
{
    uint8_t i;

    lcd_init();

    if (lcddev.id == 0u)
    {
        /* 没检出屏幕（未插或接触不良）。与 AHT20、ES8388 同样的处理原则：
         * 外设缺失不让整机停摆，采集、上报、风扇、语音一律照常。 */
        s_ready = 0u;
        return 1u;
    }

    lcd_display_dir(1);          /* 横屏。必须在 tp_init() 之前——触摸驱动会按
                                  * lcddev.dir 决定坐标映射方向 */
    (void)tp_dev.init();         /* 电阻屏路径返回 1，不代表失败，故不检查返回值 */

    /* KEY0（PE4）的引脚初始化。触发校准的判断放在 ui_screen_poll() 里，
     * 这样运行中随时按都有效，不必赶在上电那一瞬间。 */
    UI_KEY0_GPIO_CLK_ENABLE();
    {
        GPIO_InitTypeDef key_init;
        key_init.Pin = UI_KEY0_GPIO_PIN;
        key_init.Mode = GPIO_MODE_INPUT;
        key_init.Pull = GPIO_PULLUP;             /* KEY0 按下为低 */
        key_init.Speed = GPIO_SPEED_FREQ_LOW;
        HAL_GPIO_Init(UI_KEY0_GPIO_PORT, &key_init);
    }

    for (i = 0u; i < UI_ROW_COUNT; i++)
    {
        s_shadow_value[i][0] = '\0';
        s_shadow_status[i] = UI_STATUS_UNDRAWN;
    }
    s_shadow_alerts = 0u;
    s_shadow_fan = 0xFFu;
    s_shadow_audio = 0xFFu;
    s_shadow_link = 0xFFu;
    s_touch_was_down = 0u;
    s_btn_is_down = 0u;
    s_ready = 1u;

    draw_static_frame();
    return 0u;
}

/**
 * @brief       按状态码重绘某一行的状态文字
 */
static void draw_row_status(uint8_t index, uint8_t status)
{
    const char *text;
    uint16_t color;

    if (status == UI_STATUS_ALARM)
    {
        text = UI_TXT("报警");
        color = UI_COLOR_ALARM;
    }
    else if (status == UI_STATUS_INVALID)
    {
        text = UI_TXT("无效");
        color = UI_COLOR_MUTED;
    }
    else
    {
        text = UI_TXT("正常");
        color = UI_COLOR_OK;
    }

    draw_text_field(UI_STATUS_X, (uint16_t)(row_top(index) + 16u), UI_STATUS_W,
                    text, 1u, color, UI_COLOR_BG);
}

/**
 * @brief       重绘某一行的数值与状态
 * @param       text    已格式化好的 5 字符读数
 * @param       valid   本次读数是否有效
 */
static void refresh_row(uint8_t index, const char *text, uint8_t valid)
{
    uint8_t alarming = (uint8_t)((s_shadow_alerts & s_rows[index].alert_bit) != 0u);
    uint8_t status;
    uint16_t value_color;

    if (valid == 0u)
    {
        status = UI_STATUS_INVALID;
    }
    else
    {
        status = alarming ? UI_STATUS_ALARM : UI_STATUS_OK;
    }

    value_color = (status == UI_STATUS_ALARM) ? UI_COLOR_VALUE_ALARM : UI_COLOR_VALUE;

    /* 数值文本没变，但报警状态变了时也要重画——颜色要跟着变 */
    if ((strcmp(s_shadow_value[index], text) != 0) || (s_shadow_status[index] != status))
    {
        draw_text_field(UI_VALUE_X, (uint16_t)(row_top(index) + 4u), UI_VALUE_W,
                        text, 2u, value_color, UI_COLOR_BG);
        (void)snprintf(s_shadow_value[index], UI_VALUE_TEXT_LEN, "%s", text);
    }

    if (s_shadow_status[index] != status)
    {
        draw_row_status(index, status);
        s_shadow_status[index] = status;
    }
}

void ui_screen_set_values(const sensor_data_t *data)
{
    const sensor_reading_t *readings[UI_ROW_COUNT];
    uint8_t i;

    if ((s_ready == 0u) || (data == 0))
    {
        return;
    }

    /* 第二页时不画，但影子值照旧更新——否则切回第一页会看到一屏旧数值，
     * 而"只重绘变化字段"的策略认为它们没变过。 */
    if (s_page != 0u)
    {
        for (i = 0u; i < UI_ROW_COUNT; i++)
        {
            s_shadow_value[i][0] = '\0';
            s_shadow_status[i] = UI_STATUS_UNDRAWN;
        }
        return;
    }

    readings[0] = &data->temperature;
    readings[1] = &data->humidity;
    readings[2] = &data->noise;

    for (i = 0u; i < UI_ROW_COUNT; i++)
    {
        char text[UI_VALUE_TEXT_LEN];

        format_value(text, sizeof(text), readings[i]);
        refresh_row(i, text, readings[i]->valid);
    }
}

void ui_screen_set_alerts(uint8_t alert_bits)
{
    uint8_t i;

    if ((s_ready == 0u) || (alert_bits == s_shadow_alerts))
    {
        return;
    }

    s_shadow_alerts = alert_bits;

    /* 第二页时正文区画的是问答，这里不能往上面写——记下位图即可，
     * 切回第一页时 draw_body() 与下一轮 set_values() 会把状态补上。 */
    if (s_page != 0u)
    {
        return;
    }

    /* 位图变了，用上一次画上去的数值文本重新走一遍刷新逻辑——数值本身没变，
     * refresh_row() 里的比较会只重画颜色和状态字，不会整行重绘。 */
    for (i = 0u; i < UI_ROW_COUNT; i++)
    {
        if (s_shadow_status[i] != UI_STATUS_UNDRAWN)
        {
            uint8_t valid = (uint8_t)(s_shadow_status[i] != UI_STATUS_INVALID);
            char text[UI_VALUE_TEXT_LEN];

            (void)snprintf(text, sizeof(text), "%s", s_shadow_value[i]);
            refresh_row(i, text, valid);
        }
    }
}

void ui_screen_set_actuators(uint8_t fan_running, uint8_t audio_playing)
{
    if (s_ready == 0u)
    {
        return;
    }

    fan_running = (uint8_t)(fan_running != 0u);
    audio_playing = (uint8_t)(audio_playing != 0u);

    if (fan_running != s_shadow_fan)
    {
        draw_text_field(UI_FAN_STATE_X, UI_ACT_TEXT_Y, UI_LABEL_W,
                        fan_running ? UI_TXT("运行") : UI_TXT("停止"), 1u,
                        fan_running ? UI_COLOR_OK : UI_COLOR_MUTED, UI_COLOR_BG);
        s_shadow_fan = fan_running;
    }

    if (audio_playing != s_shadow_audio)
    {
        draw_text_field(UI_AUDIO_STATE_X, UI_ACT_TEXT_Y, UI_LABEL_W,
                        audio_playing ? UI_TXT("播报") : "", 1u,
                        UI_COLOR_ALARM, UI_COLOR_BG);
        s_shadow_audio = audio_playing;
    }
}

void ui_screen_set_link(uint8_t linked)
{
    if (s_ready == 0u)
    {
        return;
    }

    linked = (uint8_t)(linked != 0u);
    if (linked == s_shadow_link)
    {
        return;
    }

    draw_text_field(UI_LINK_X, 1u, UI_LINK_W,
                    linked ? UI_TXT("已连接") : UI_TXT("未连接"), 1u,
                    UI_COLOR_TITLE_FG, UI_COLOR_TITLE_BG);
    s_shadow_link = linked;
}

/**
 * @brief       重绘按钮底色，给出按下的视觉反馈
 */
void ui_screen_set_answer(uint8_t kind, uint8_t channel, uint16_t value_x10,
                          uint16_t limit_x10, uint8_t flags, uint8_t source)
{
    if (s_ready == 0u)
    {
        return;
    }

    s_answer_kind = kind;
    s_answer_channel = channel;
    s_answer_value = value_x10;
    s_answer_limit = limit_x10;
    s_answer_flags = flags;
    s_answer_source = source;

    /* 不在第二页就只记不画。切页时 draw_body() 会把它画出来——这样一条在
     * 第一页时到达的答案不会丢，也不会去动当前正在看的那一页。 */
    if (s_page == 1u)
    {
        draw_body();
    }
}

/**
 * @brief       切换页签
 * @param       page    0=数据 1=问答
 */
static void switch_page(uint8_t page)
{
    if ((page == s_page) || (page >= UI_TAB_COUNT))
    {
        return;
    }

    s_page = page;
    draw_tab(0u, (uint8_t)(s_page == 0u));
    draw_tab(1u, (uint8_t)(s_page == 1u));

    /* 影子值全部作废：正文区刚被擦掉，"只重绘变化字段"的策略必须重新认为
     * 每个字段都需要画，否则切回第一页会停在一片空白上。 */
    ui_screen_invalidate();
    draw_body();
    debug_log_printf("[lcd] page=%u\r\n", (unsigned int)s_page);
}

static void draw_button(uint8_t pressed)
{
    uint16_t bg = pressed ? UI_COLOR_BTN_BG_DOWN : UI_COLOR_BTN_BG;
    uint16_t fg = pressed ? WHITE : UI_COLOR_BTN_FG;

    lcd_fill(UI_BTN_X0, UI_BTN_Y0, UI_BTN_X1, UI_BTN_Y1, bg);
    draw_text_field(UI_BTN_TEXT_X, UI_BTN_TEXT_Y, 96u, UI_TXT("语音自检"), 1u, fg, bg);
}

/**
 * @brief       把所有影子状态置为"未画过"，强制下一轮全部重绘
 * @note        校准界面会把整屏覆盖掉，回来后必须让每个字段都认为自己需要重画，
 *              否则"只重绘变化字段"的策略会让屏幕停留在校准残留的画面上。
 */
static void ui_screen_invalidate(void)
{
    uint8_t i;

    for (i = 0u; i < UI_ROW_COUNT; i++)
    {
        s_shadow_value[i][0] = '\0';
        s_shadow_status[i] = UI_STATUS_UNDRAWN;
    }
    s_shadow_fan = 0xFFu;
    s_shadow_audio = 0xFFu;
    s_shadow_link = 0xFFu;
}

/**
 * @brief       KEY0 是否按下（PE4，低电平有效）
 */
static uint8_t ui_key0_pressed(void)
{
    return (uint8_t)(HAL_GPIO_ReadPin(UI_KEY0_GPIO_PORT, UI_KEY0_GPIO_PIN)
                     == GPIO_PIN_RESET);
}

ui_event_t ui_screen_poll(void)
{
    ui_event_t event = UI_EVENT_NONE;
    uint8_t down;

    if (s_ready == 0u)
    {
        return UI_EVENT_NONE;
    }

    /* KEY0（PE4）随时按下 → 重新做五点触摸校准。
     *
     * 【为什么运行中也能触发，而不只在开机瞬间】最初只在 ui_screen_init() 里查一次，
     * 实测发现要求太苛刻——必须在上电那一刻正好按住，运行中按毫无反应，
     * 用户无从判断是"固件没这个功能"还是"没按对时机"。厂商自己的例程也是在
     * 主循环里查 KEY0 触发 tp_adjust()（见实验28 main.c），照此改为随时可触发。
     *
     * 【为什么需要重新校准】厂商的 tp_init() 只在 24C02 里没有校准标记时才校准。
     * 开发板出厂测试程序很可能已经写过一份**竖屏**下做的校准值，而本项目跑横屏，
     * 坐标换算方向不同——校准数据"存在"但完全不可用，点屏幕有响应、算出的坐标
     * 却落在别处，表现就是"怎么点都没反应"。厂商代码无法察觉这种情况。
     *
     * tp_adjust() 是阻塞的，点满五个点才返回；期间采集与上报暂停，这是用户主动
     * 按键换来的，可以接受。返回后必须让整屏重绘（校准界面把画面覆盖了）。 */
    if (ui_key0_pressed() != 0u)
    {
        debug_log_printf("[lcd] KEY0 pressed, running touch calibration\r\n");
        tp_adjust();                 /* 内部会把结果写回 24C02 */
        ui_screen_invalidate();
        draw_static_frame();
        s_touch_was_down = 0u;
        s_btn_is_down = 0u;
        return UI_EVENT_NONE;
    }

    /* 必须查 tp_dev.sta，**不能用 tp_dev.scan() 的返回值**。
     *
     * 厂商的 tp_scan() 写的是 `return tp_dev.sta & TP_PRES_DOWN;`，而
     * TP_PRES_DOWN 是 0x8000、函数返回类型却是 uint8_t——按下时 0x8000 截断成
     * uint8_t 恒为 0，**这个返回值永远是 0**。厂商自己的例程也从不看它，一律是
     * 「先 scan(0)，再单独判 tp_dev.sta & TP_PRES_DOWN」（见实验28 main.c 的
     * rtp_test）。此处照抄那个用法。
     *
     * 2026-09-08 实机反馈"屏幕怎么点都没反应"就是踩了这个返回值。 */
    (void)tp_dev.scan(0);
    down = (uint8_t)((tp_dev.sta & TP_PRES_DOWN) != 0u);

    if ((down != 0u) && (s_touch_was_down == 0u))
    {
        /* 按下沿。只在这一刻判定，按住不放不会连续触发——喇叭一次只能说一句，
         * 连发请求毫无意义。 */
        uint16_t x = tp_dev.x[0];
        uint16_t y = tp_dev.y[0];

        /* 页签先判。两块区域不重叠（页签在标题栏，按钮在底栏），先判哪个都一样，
         * 写在前面只是让"点上面换页、点下面播报"这个关系一眼可见。 */
        if ((y >= UI_TAB_Y0) && (y <= UI_TAB_Y1))
        {
            if ((x >= UI_TAB0_X0) && (x < (uint16_t)(UI_TAB0_X0 + UI_TAB_W)))
            {
                switch_page(0u);
            }
            else if ((x >= UI_TAB1_X0) && (x < (uint16_t)(UI_TAB1_X0 + UI_TAB_W)))
            {
                switch_page(1u);
            }
        }
        else if ((x >= UI_BTN_X0) && (x <= UI_BTN_X1) && (y >= UI_BTN_Y0) && (y <= UI_BTN_Y1))
        {
            event = UI_EVENT_SELF_TEST;
            s_btn_is_down = 1u;
            draw_button(1u);
        }
    }
    else if ((down == 0u) && (s_touch_was_down != 0u) && (s_btn_is_down != 0u))
    {
        s_btn_is_down = 0u;
        draw_button(0u);
    }

    s_touch_was_down = (uint8_t)(down != 0u);
    return event;
}
