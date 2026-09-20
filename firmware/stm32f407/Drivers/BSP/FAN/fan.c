/**
 ****************************************************************************************************
 * @file        fan.c
 * @brief       小风扇模块 ATK-MB023 驱动实现，接口说明见 fan.h
 *
 * 【2026-09-08 修改】FI 由"普通 GPIO 拉高 = 全速"改为 TIM9_CH1 输出 PWM 调速。
 * 起因是实机反馈：全速转速过高，且持续运行一段时间后驱动可能进入过热保护。
 * 本项目要的是持续换气而不是最大风量，全速既没必要也不可持续。
 *
 * 接线一根都没变——PE5 在 STM32F407 上的 AF3 正是 TIM9_CH1。
 * BI(PE6) 仍是恒低的普通 GPIO，从结构上保证 FI/BI 不会同时为高（SS6285L 的刹车态）。
 ****************************************************************************************************
 */

#include "./BSP/FAN/fan.h"
#include "./SYSTEM/delay/delay.h"

/* 当前风扇状态。由 fan_set() 维护，供 fan_is_running() 查询——
 * 不去读 GPIO 回读寄存器，是因为这里要表达的是"我们命令它转"这一意图，
 * 与引脚电平是否被外部拉动无关。 */
static uint8_t s_fan_running = 0u;

/* 当前占空比设定（1~100）。风扇停止时仍然保留，下次启动直接采用。 */
static uint8_t s_fan_duty = FAN_DEFAULT_DUTY_PERCENT;

static TIM_HandleTypeDef s_fan_tim;

/**
 * @brief       把百分比换算成比较寄存器值并写入
 * @note        只改 CCR，不停定时器——PWM 占空比可以在运行中平滑改变。
 */
static void fan_apply_duty(uint8_t percent)
{
    uint32_t compare = ((uint32_t)(FAN_PWM_PERIOD + 1u) * percent) / 100u;

    __HAL_TIM_SET_COMPARE(&s_fan_tim, FAN_PWM_CHANNEL, compare);
}

/**
 * @brief       初始化风扇控制引脚，并确保风扇处于停止状态
 */
void fan_init(void)
{
    GPIO_InitTypeDef gpio_init_struct;
    TIM_OC_InitTypeDef oc_init_struct;

    FAN_FI_GPIO_CLK_ENABLE();
    FAN_BI_GPIO_CLK_ENABLE();
    FAN_PWM_CLK_ENABLE();

    /* FI：复用推挽，接到 TIM9_CH1 */
    gpio_init_struct.Pin = FAN_FI_GPIO_PIN;
    gpio_init_struct.Mode = GPIO_MODE_AF_PP;
    gpio_init_struct.Pull = GPIO_NOPULL;
    gpio_init_struct.Speed = GPIO_SPEED_FREQ_HIGH;    /* 20kHz PWM，边沿要干净 */
    gpio_init_struct.Alternate = FAN_FI_GPIO_AF;
    HAL_GPIO_Init(FAN_FI_GPIO_PORT, &gpio_init_struct);

    /* BI：普通推挽输出，恒为低 */
    gpio_init_struct.Pin = FAN_BI_GPIO_PIN;
    gpio_init_struct.Mode = GPIO_MODE_OUTPUT_PP;
    gpio_init_struct.Pull = GPIO_NOPULL;
    gpio_init_struct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(FAN_BI_GPIO_PORT, &gpio_init_struct);
    HAL_GPIO_WritePin(FAN_BI_GPIO_PORT, FAN_BI_GPIO_PIN, GPIO_PIN_RESET);

    s_fan_tim.Instance = FAN_PWM_TIMX;
    s_fan_tim.Init.Prescaler = 0u;                    /* 168MHz 直接分频到 20kHz */
    s_fan_tim.Init.CounterMode = TIM_COUNTERMODE_UP;
    s_fan_tim.Init.Period = FAN_PWM_PERIOD;
    s_fan_tim.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    s_fan_tim.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&s_fan_tim);

    oc_init_struct.OCMode = TIM_OCMODE_PWM1;
    oc_init_struct.Pulse = 0u;                        /* 上电即停 */
    oc_init_struct.OCPolarity = TIM_OCPOLARITY_HIGH;
    oc_init_struct.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&s_fan_tim, &oc_init_struct, FAN_PWM_CHANNEL);

    HAL_TIM_PWM_Start(&s_fan_tim, FAN_PWM_CHANNEL);

    s_fan_duty = FAN_DEFAULT_DUTY_PERCENT;
    fan_set(0u);                                       /* 上电即停 */
}

/**
 * @brief       设置风扇运行状态
 * @param       on : 非 0 = 按当前占空比转，0 = 停
 */
void fan_set(uint8_t on)
{
    if (on != 0u)
    {
        /* 启动脉冲：直流电机的启动转矩需求高于运行时，直接给 60% 有可能通电不转。
         * 先满占空比冲一下再落回设定值，是电机驱动的常规做法。
         *
         * 这里阻塞 150ms 是可以接受的：风扇启停只在阈值穿越时发生，远低于每个
         * 采集周期都要阻塞 80~100ms 的 AHT20 读取；为它单开一个非阻塞状态机
         * 得不偿失。 */
        if (s_fan_running == 0u)
        {
            fan_apply_duty(100u);
            delay_ms(FAN_KICKSTART_MS);
        }
        fan_apply_duty(s_fan_duty);
        s_fan_running = 1u;
    }
    else
    {
        fan_apply_duty(0u);
        s_fan_running = 0u;
    }
}

/**
 * @brief       设置风扇占空比（1~100）
 */
void fan_set_duty(uint8_t percent)
{
    if (percent < 1u)
    {
        percent = 1u;
    }
    else if (percent > 100u)
    {
        percent = 100u;
    }

    s_fan_duty = percent;

    /* 正在转就立即生效；停着就只记下来，下次启动时采用。 */
    if (s_fan_running != 0u)
    {
        fan_apply_duty(s_fan_duty);
    }
}

/**
 * @brief       查询当前占空比设定
 */
uint8_t fan_get_duty(void)
{
    return s_fan_duty;
}

/**
 * @brief       查询风扇当前状态
 * @retval      1 = 正在转，0 = 已停止
 */
uint8_t fan_is_running(void)
{
    return s_fan_running;
}
