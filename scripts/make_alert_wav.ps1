# 生成四句告警语音的 WAV 源文件，供 scripts/wav_to_c.py 转成固件里的 PCM 表。
#
# 用 Windows 自带的 SAPI（System.Speech）合成，**不需要安装任何东西**，也不联网。
# 之所以用 PowerShell 而不是 Python：SAPI 是 Windows COM 组件，Python 侧要用它得
# 装 pywin32/comtypes；而固件工具链（Keil）本来就只在 Windows 上跑，多一个
# Windows-only 的资产生成脚本不引入任何新的可移植性问题，却省掉一个依赖。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\make_alert_wav.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\make_alert_wav.ps1 -Rate 0
#
# 生成后再跑（顺序必须是 温度/湿度/噪声/湿度过高，与固件 audio_alert_id_t 一致）：
#   python scripts/wav_to_c.py firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/wav/温度.wav `
#                              firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/wav/湿度.wav `
#                              firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/wav/噪声.wav `
#                              firmware/stm32f407/Drivers/BSP/AUDIO_ALERT/wav/湿度过高.wav

param(
    # 语速。2026-10-01 由 +2 调为 +1：用户实听反映偏快，"温度超标"只听得清"超标"。
    # 以下是 +2 时的取舍记录：一句约 1.4 秒，三句共约 134 KB Flash，
    # 一次播报的噪声消隐窗口约 4.4 秒（播报时长 + 3 秒混响尾巴），正好跨
    # 1~2 个采集周期。语速 0 会让三句涨到 166 KB、消隐 4.8 秒；把文案加长到
    # "温度超过报警阈值，请注意"更是要 405 KB、消隐 7.2 秒——那是 40% 的 Flash
    # 换三句话，而且会连丢 2~3 个周期的噪声数据，而噪声正是验证记录里统计
    # Modbus 应答成功率的那个通道。
    [int]$Rate = 1,

    # 采样率必须与固件 audio_alert.h 的 AUDIO_ALERT_SAMPLE_RATE 一致。
    # 直接按这个率合成，wav_to_c.py 就不需要重采样。
    [int]$SampleRate = 16000,

    [string]$Voice = "Microsoft Huihui Desktop",

    [string]$OutDir = "$PSScriptRoot\..\firmware\stm32f407\Drivers\BSP\AUDIO_ALERT\wav"
)

# 四句文案。顺序即 audio_alert_id_t 的顺序，改动这里必须同步 wav_to_c.py 的调用顺序。
#
# "湿度过高"是 2026-10-01 补的第四句，追加在末尾以保持前三句的编号不变。
# 此前湿度上限（75%）已于 09-08 加入，但语音只有"湿度过低"一句，而播报按通道选句，
# 湿度偏高时喇叭说的也是"湿度过低"。现在 service/alarm_announcer.py 按越限方向选句。
#
# "湿度过低"而不是"湿度超标"：湿度的报警规则是 BELOW_MIN（低于 30%），
# 与温度、噪声的 ABOVE_MAX 方向相反，见 src/service/sensor_data_processor.py。
# 说成"超标"会与实际判定相反。
$Phrases = [ordered]@{
    "温度" = "温度超标"
    "湿度" = "湿度过低"
    "噪声" = "噪声超标"
    "湿度过高" = "湿度过高"
}

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

$installed = $synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
if ($installed -notcontains $Voice) {
    Write-Error "找不到语音 '$Voice'。本机可用：$($installed -join ', ')"
    exit 1
}
$synth.SelectVoice($Voice)
$synth.Rate = $Rate

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    $SampleRate,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$total = 0

foreach ($name in $Phrases.Keys) {
    $path = Join-Path $OutDir "$name.wav"
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($Phrases[$name])
    $synth.SetOutputToNull()

    $bytes = (Get-Item $path).Length
    $total += $bytes
    "{0,-6} `"{1}`"  {2,7} 字节  {3,5:N2} 秒" -f "$name.wav", $Phrases[$name], $bytes, (($bytes - 44) / ($SampleRate * 2))
}

$synth.Dispose()
"",
"语音 : $Voice   语速 : $Rate   采样率 : $SampleRate Hz 单声道 16bit",
("合计 : {0:N1} KB（固件 Flash 占用与此接近）" -f ($total / 1024)),
"输出 : $(Resolve-Path $OutDir)" | Write-Output
