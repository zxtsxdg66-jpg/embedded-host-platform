from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.intent import (
    is_question_clause,
    recognise,
    split_clauses,
)
from service.assistant.models import IntentKind

# -- 分句（2026-09-15） --------------------------------------------------------


def test_clauses_split_on_punctuation_and_spaces() -> None:
    assert split_clauses("现在多少度啊 有点热 你可以帮我打开风扇嘛") == [
        "现在多少度啊",
        "有点热",
        "你可以帮我打开风扇嘛",
    ]
    assert split_clauses("风扇开着吗？温度多少") == ["风扇开着吗？", "温度多少"]


def test_a_space_next_to_a_number_does_not_split_it_off() -> None:
    """拆开的话指令只剩"通风阈值调到"，数值读不到，指令会被拒。"""
    assert split_clauses("现在多少度 通风阈值调到 28 度") == [
        "现在多少度",
        "通风阈值调到 28 度",
    ]
    assert split_clauses("调到 26.5 度") == ["调到 26.5 度"]


def test_a_feeling_is_not_a_question_clause() -> None:
    for clause in ("有点热", "太热了", "这么吵"):
        assert not is_question_clause(clause), clause
    for clause in ("现在多少度啊", "湿度呢", "风扇开着吗？", "噪声多大"):
        assert is_question_clause(clause), clause


def test_a_not_a_and_mei_questions_count_as_questions() -> None:
    """两两组合题库里拖后腿的问法：不认它们，复合句里这一问会被整段当成铺垫。"""
    for clause in (
        "外面冷不冷", "潮不潮", "吵不吵", "温度超了没有", "风扇开了没",
        "最闹腾的时候有多响",
    ):
        assert is_question_clause(clause), clause

# -- channel identification ---------------------------------------------------


def test_recognises_each_channel_by_its_common_names() -> None:
    for question, channel in (
        ("现在温度多少", TEMPERATURE_CHANNEL),
        ("气温多少度", TEMPERATURE_CHANNEL),
        ("湿度多少", HUMIDITY_CHANNEL),
        ("现在噪声多大", NOISE_CHANNEL),
        ("噪音多少分贝", NOISE_CHANNEL),
    ):
        assert recognise(question).channel == channel, question


def test_plain_channel_question_is_a_current_value_question() -> None:
    intent = recognise("现在温度多少")
    assert intent.kind is IntentKind.CURRENT_VALUE
    assert intent.channel == TEMPERATURE_CHANNEL


# -- statistics ---------------------------------------------------------------


def test_statistic_words_select_the_right_kind() -> None:
    assert recognise("温度平均多少").kind is IntentKind.AVERAGE
    assert recognise("温度最高多少").kind is IntentKind.MAXIMUM
    assert recognise("温度最低多少").kind is IntentKind.MINIMUM


def test_statistic_still_carries_the_channel() -> None:
    assert recognise("噪声平均多少").channel == NOISE_CHANNEL


# -- precedence rules (the ordering in recognise() is deliberate) -------------


def test_threshold_beats_alarm_state() -> None:
    """"噪声阈值是多少" asks for a configured constant, not for whether
    the current reading is over it. Getting this backwards would answer
    "是的，超标了" to a question about the standard."""
    intent = recognise("噪声的阈值是多少")
    assert intent.kind is IntentKind.THRESHOLD_INFO
    assert intent.channel == NOISE_CHANNEL


def test_alarm_state_is_recognised_when_no_threshold_word_present() -> None:
    intent = recognise("噪声超标了吗")
    assert intent.kind is IntentKind.ALARM_STATE
    assert intent.channel == NOISE_CHANNEL


def test_fan_beats_channel() -> None:
    """"温度高了风扇会转吗" mentions both; the subject is the fan."""
    assert recognise("温度高了风扇会转吗").kind is IntentKind.FAN_STATE
    assert recognise("风扇为什么在转").kind is IntentKind.FAN_STATE


def test_help_beats_everything() -> None:
    assert recognise("你能干什么").kind is IntentKind.HELP


# -- fallback behaviour -------------------------------------------------------


def test_unknown_question_falls_back_to_help() -> None:
    """Guessing a channel for an unrelated question would answer
    confidently and wrongly; HELP lists what can be asked instead."""
    assert recognise("今天星期几").kind is IntentKind.HELP
    assert recognise("地铁几点收班").kind is IntentKind.HELP


def test_empty_question_is_help_not_a_crash() -> None:
    assert recognise("").kind is IntentKind.HELP
    assert recognise("   ").kind is IntentKind.HELP


def test_device_list_question() -> None:
    assert recognise("有几个设备在线").kind is IntentKind.DEVICE_LIST


def test_english_keywords_also_work() -> None:
    assert recognise("what is the temperature").channel == TEMPERATURE_CHANNEL
    assert recognise("noise alarm?").kind is IntentKind.ALARM_STATE


# -- instructions -------------------------------------------------------------


def test_fan_instructions_are_told_apart_from_a_fan_question() -> None:
    assert recognise("把风扇打开").kind is IntentKind.FAN_ON
    assert recognise("关掉风扇").kind is IntentKind.FAN_OFF
    assert recognise("风扇交给自动").kind is IntentKind.FAN_AUTO
    assert recognise("风扇在转吗").kind is IntentKind.FAN_STATE


def test_a_command_word_alone_is_not_a_fan_command() -> None:
    """A sentence must name the fan before any word in it can be read as an
    instruction -- otherwise "把灯关掉" would stop the ventilation.

    2026-09-09 起这类句子归 BARE_SWITCH，会被反问而不是回帮助文案。
    本用例要守的东西没变，并且写得更直白了：**不许产生动作**。
    落到帮助文案还是落到反问都不产生动作，前者当时是唯一的选项。"""
    from service.assistant.control import CONTROL_KINDS

    for question in ("把灯关掉", "打开", "那你开开呗"):
        assert recognise(question).kind not in CONTROL_KINDS, question
    assert recognise("打开").kind is IntentKind.BARE_SWITCH


def test_setting_a_ventilation_threshold_beats_the_plain_on_off_reading() -> None:
    """"把通风阈值调到 28 度" also contains a fan word; reading it as "turn
    on" would act on the wrong thing entirely."""
    intent = recognise("把通风温度阈值调到 28 度")
    assert intent.kind is IntentKind.SET_VENT_THRESHOLD
    assert intent.channel == TEMPERATURE_CHANNEL


def test_a_unit_stands_in_for_a_missing_channel_word() -> None:
    """"通风阈值调到 28 度" names no channel, but 度 does."""
    assert recognise("通风阈值调到 28 度").channel == TEMPERATURE_CHANNEL
    assert recognise("通风阈值调到 75%").channel == HUMIDITY_CHANNEL


def test_asking_about_an_alarm_threshold_is_still_a_question() -> None:
    """The alarm thresholds are fixed (argued from a
    standard); only the ventilation ones move, and only when the sentence
    names ventilation."""
    assert recognise("噪声阈值是多少").kind is IntentKind.THRESHOLD_INFO
    assert recognise("温度报警阈值是多少").kind is IntentKind.THRESHOLD_INFO


def test_a_threshold_instruction_without_a_number_is_still_an_instruction() -> None:
    """Found in a demo dry-run: "调低一点" was being read as a question and
    answered with the fan's state. Understanding it and then refusing to
    guess how far is the honest outcome."""
    assert recognise("把通风温度阈值调低一点").kind is IntentKind.SET_VENT_THRESHOLD


def test_colloquial_superlatives_are_statistics_not_current_values() -> None:
    """Also from the dry-run: "最吵到多少" answered with the reading at that
    instant -- not a wrong number, which is what made it easy to miss."""
    assert recognise("这一阵子最吵到多少").kind is IntentKind.MAXIMUM
    assert recognise("最安静的时候噪声多少").kind is IntentKind.MINIMUM


def test_the_actuator_can_be_named_colloquially() -> None:
    """From a rehearsal run: "那个吹风的" named the fan in a way the rules
    did not know, so the sentence went to the model -- which got it right
    only about half the time. A word the rules know is instant and
    identical every time."""
    assert recognise("太热了让那个吹风的转起来").kind is IntentKind.FAN_ON


def test_a_unit_alone_locates_the_channel_in_a_question() -> None:
    """"这一阵子平均多少度"没点名通道，但"度"就足以定位到温度。
    只在问句里做这一步兜底——把一条没说清对象的指令猜成某个通道是危险的。"""
    intent = recognise("这一阵子平均多少度")

    assert intent.kind is IntentKind.AVERAGE
    assert intent.channel == TEMPERATURE_CHANNEL
    assert recognise("现在多少度").channel == TEMPERATURE_CHANNEL


def test_colloquial_vocabulary_added_from_a_65_question_batch() -> None:
    """这一批词全部来自实测：65 句连问里规则落空、只能交给模型的那些。
    规则认得的说法零延迟且每次一致，比继续调提示词划算。"""
    assert recognise("最干的时候湿度多少").kind is IntentKind.MINIMUM
    assert recognise("平时湿度大概在什么水平").kind is IntentKind.AVERAGE
    assert recognise("温度超了没有").kind is IntentKind.ALARM_STATE
    assert recognise("声音大不大").channel == NOISE_CHANNEL
    assert recognise("平时安静的时候大概多少").channel == NOISE_CHANNEL


def test_asking_where_the_line_is_beats_asking_whether_it_was_crossed() -> None:
    """"湿度低于多少会报警"里同时有"报警"和"低于多少"：问的是那条线画在哪，
    不是现在越没越线。阈值词表先于报警词表被检查，正是为此。"""
    intent = recognise("湿度低于多少会报警")

    assert intent.kind is IntentKind.THRESHOLD_INFO
    assert intent.channel == HUMIDITY_CHANNEL
    assert recognise("多大声算超标").kind is IntentKind.THRESHOLD_INFO



# -- requests to speak on demand ----------------------------------------------


def test_asking_the_system_to_speak_is_recognised_rather_than_answered() -> None:
    """"试一下语音播报能不能响"此前落到噪声通道——响与声音都是噪声关键词——
    于是一条系统办不到的请求拿到了一个真实声压级。认出它才谈得上拒绝它。"""
    for question in (
        "测试一下报警发声",
        "试一下语音播报能不能响",
        "播报一下",
        "你能播报一下吗",
        "喇叭响不响",
    ):
        assert recognise(question).kind is IntentKind.ANNOUNCE_REQUEST, question


def test_a_sound_word_alone_is_still_a_noise_question() -> None:
    """响、声音、吵都是噪声通道的词，单独出现时问的是读数。
    只有再配上"试试""能不能"这类试探词，才读成请求播报——
    两半都要求，正因为任一半单独出现时都有正常含义。"""
    assert recognise("外面很响吗").channel == NOISE_CHANNEL
    assert recognise("现在噪声多少").kind is IntentKind.CURRENT_VALUE
    assert recognise("安静吗").channel == NOISE_CHANNEL

    # 反过来：只有试探词、没有声音词，仍按原意分类
    assert recognise("试一下温度最高多少").kind is IntentKind.MAXIMUM

    # 两半齐了才算
    assert recognise("让它响一声试试").kind is IntentKind.ANNOUNCE_REQUEST


def test_speaking_is_not_in_the_control_whitelist() -> None:
    """播报要构造 ALERT_* 命令帧直接驱动硬件，而白名单里的四项只改通风设置；
    且播出去撤不回来。两条都与 control 模块的准入性质相抵，故只认出、不执行。"""
    from service.assistant.control import CONTROL_KINDS

    assert IntentKind.ANNOUNCE_REQUEST not in CONTROL_KINDS


# -- 删除请求：认出但拒绝（2026-09-18） ---------------------------------------


def test_a_request_to_delete_data_is_recognised() -> None:
    """与播报同一个理由，也是同一个具体隐患：数据在日常句子里紧挨着通道词
    （"把噪声数据清一清"），没有自己的分支时会被通道分支抢走，
    于是一条要求**删除**的话拿回来一个真实读数。认出它才谈得上拒绝它。"""
    for question in (
        "把旧数据删了",
        "删除历史记录",
        "清空数据库",
        "把三天前的数据清理掉",
        "数据太多了，清一清",
        "能不能删掉上传的文件",
        "把噪声数据清一清",
        "把云上的数据删干净",
    ):
        assert recognise(question).kind is IntentKind.DELETE_REQUEST, question


def test_清楚_is_not_a_deletion_word() -> None:
    """词表里刻意不收单字「清」——它长在「清楚」里，而「说清楚点」
    是对助手说的一句再正常不过的话，单字匹配会把它变成一句拒绝。"""
    assert recognise("说清楚点").kind is not IntentKind.DELETE_REQUEST
    assert recognise("这个数据清楚吗").kind is not IntentKind.DELETE_REQUEST
    assert recognise("帮我看清楚现在几度").kind is not IntentKind.DELETE_REQUEST


def test_turning_the_fan_off_is_never_read_as_deleting() -> None:
    """词表里也不收「掉」或「关掉」——那是关风扇的说法。
    只有删/清打头的词才算，所以一条关机指令不会被读成删除请求。"""
    assert recognise("把风扇关掉").kind is IntentKind.FAN_OFF
    assert recognise("把风扇关了").kind is IntentKind.FAN_OFF
    assert recognise("关了吧").kind is IntentKind.BARE_SWITCH


def test_deleting_is_not_in_the_control_whitelist() -> None:
    """删除三条准入性质全不满足：不可逆、参数取不自用户原话、没有撤销。
    比播报更重——播报最坏响一声，删除最坏是数据没了。
    也**不走上云那套按钮方案**：2026-09-17 已经判定过按钮对删除太弱
    （"清空历史记录"因此被收窄成只清显示），在按钮前面再接一个模型不会让它变强。"""
    from service.assistant.control import CONTROL_KINDS

    assert IntentKind.DELETE_REQUEST not in CONTROL_KINDS


def test_an_existing_question_bank_sentence_is_not_stolen() -> None:
    """这个分支是早返回，抢错一句就会顶掉原来的答案。
    87 句基线与 148 句留出题库当日实测零命中，这里钉住最容易被抢的几句。"""
    for question in (
        "现在温度多少",
        "噪声超标了吗",
        "温度最高是多少",
        "你能干什么",
        "有几个设备在线",
        "把通风阈值调到28度",
    ):
        assert recognise(question).kind is not IntentKind.DELETE_REQUEST, question


# -- fan instructions, widened 2026-09-09 -------------------------------------


def test_the_shortest_way_to_say_it_is_recognised() -> None:
    """真人试用里连说三句要开风扇全部失败，第四句"打开"才成功——而它是靠模型
    兜底认出的。词表当时有"打开/开启/开一下/开起来"，唯独没有最短的"开"。
    题库测不出：四条例句每条都恰好含词表里已有的词，二者互为印证。"""
    for question in (
        "开风扇",
        "能开风扇不",
        "把风扇开了",
        "风扇开",
        "开开风扇",
        "帮我开风扇",
        "可以开风扇吗",
        "风扇能开吗",
    ):
        assert recognise(question).kind is IntentKind.FAN_ON, question


def test_widening_the_verb_does_not_turn_questions_into_orders() -> None:
    """词表放宽到裸的"开"之后，"风扇开着吗"里的"开"也会命中。
    中文在这里不靠句法区分祈使与疑问——"能开风扇吗"是请求、"风扇开着吗"是提问，
    两句都以"吗"收尾——所以界线画在**状态词**（开着／在转／开了没）上。"""
    for question in (
        "风扇在转吗",
        "风扇开着吗",
        "风扇开了没",
        "那个吹风的开着没",
        "风扇为什么在转",
        "风扇状态",
        "风扇是自动的吗",
        "风扇什么时候开",
    ):
        assert recognise(question).kind is IntentKind.FAN_STATE, question


def test_a_negated_instruction_reads_as_off_not_on() -> None:
    """"别开风扇"里含有"开"。否定词表先于开启词表被检查，正是为此。"""
    assert recognise("别开风扇").kind is IntentKind.FAN_OFF
    assert recognise("不用开风扇").kind is IntentKind.FAN_OFF
    assert recognise("把风扇关了").kind is IntentKind.FAN_OFF


def test_handing_back_to_the_system_is_auto_even_without_the_word() -> None:
    """2026-09-14 留出题库查出的唯一一处有副作用的误判："风扇让系统自己决定开关"
    意思是交回自动，却因为没有"自动"二字落到了关闭词表——"开关"里的"关"
    把风扇真的切成了手动常关。"""
    for question in (
        "风扇让系统自己决定开关",
        "风扇交给系统吧",
        "通风让系统来定",
        "风扇由系统控制",
    ):
        assert recognise(question).kind is IntentKind.FAN_AUTO, question


def test_the_same_words_asked_as_a_question_stay_a_question() -> None:
    """把"系统决定"这类说法加进自动词表后，同样的词出现在问句里不许被执行。
    守卫往"当作提问"的方向偏：误判成提问只是没执行，误判成指令会改设备状态。
    "我自己控制风扇"是手动的意思，因此"自己控制"不在自动词表里。"""
    for question in ("风扇是系统决定的吗", "风扇是系统控制的吗"):
        assert recognise(question).kind is IntentKind.FAN_STATE, question
    assert recognise("我自己控制风扇").kind is not IntentKind.FAN_AUTO
    assert recognise("关掉风扇").kind is IntentKind.FAN_OFF


def test_asking_whether_the_fan_should_run_is_not_an_order() -> None:
    """2026-09-14 的 32 句鲁棒性实验：七句征询语气的话有五句被直接执行。
    这些句子与命令在关键词层面同形，差别只在语气——"风扇是不是该开了"里
    除了一个"开"没有任何状态词，靠 ``_FAN_STATE_WORDS`` 拦不住。
    落点是 FAN_STATE，它取到的事实里本就带着通风阈值与当前读数。"""
    for question in (
        "风扇是不是该开了",
        "假设温度到了35度风扇会不会开",
        "温度超过30度就开风扇对吧",
        "要不要把风扇打开你说呢",
        "该不该开风扇",
        "如果太热了就把风扇打开",
    ):
        assert recognise(question).kind is IntentKind.FAN_STATE, question


def test_consulting_about_a_threshold_answers_the_threshold() -> None:
    """"太热了是不是该把通风阈值调到20度"整句都在征求意见，原先却真把阈值改了。
    问到阈值的句子答阈值本身，通道仍由句中的词认出（"太热了"里的"热"）。"""
    intent = recognise("太热了是不是该把通风阈值调到20度")
    assert intent.kind is IntentKind.THRESHOLD_INFO
    assert intent.channel == TEMPERATURE_CHANNEL


def test_the_guard_does_not_swallow_real_commands() -> None:
    """守卫偏向"当作提问"，但请求的常见说法不能被一起收走：
    "能开风扇不"是真实用户说过的一句命令，所以"能不能"不在征询词表里。"""
    assert recognise("把风扇打开").kind is IntentKind.FAN_ON
    assert recognise("能开风扇不").kind is IntentKind.FAN_ON
    assert recognise("风扇别开了吧").kind is IntentKind.FAN_OFF
    assert recognise("关掉风扇").kind is IntentKind.FAN_OFF
    assert recognise("把通风阈值调到28度").kind is IntentKind.SET_VENT_THRESHOLD


def test_a_negated_off_is_not_an_order_to_switch_off() -> None:
    """2026-09-25 边界题库："不要关风扇"里含"关"，被读成关风扇并真的执行——意思
    正好反了，而且模型单独判也是关风扇，复核拦不住。"别关"要的是维持现状，不是
    一条新指令，落点与征询语气相同：答风扇状态，不动执行器。

    "别开风扇"读成关闭则不变（见 ``test_a_negated_instruction_reads_as_off_not_on``）：
    自动模式下风扇随时可能自己转起来，"别开"切到手动常关才算兑现了这句话。"""
    for question in ("不要关风扇", "别关风扇", "不用关风扇", "风扇别停", "风扇不要停"):
        assert recognise(question).kind is IntentKind.FAN_STATE, question


def test_a_retracted_instruction_is_not_carried_out() -> None:
    """2026-09-25 边界题库："把风扇打开，开玩笑的"被照常执行。句中出现撤回的说法时
    整句当作提问，与征询语气同一个落点。

    代价是"算了，还是把风扇开了吧"这种先撤回再下令的句子也不执行——误判方向
    偏向"当作提问"：没执行，用户再说一句就是了；执行错了，风扇已经转了。"""
    for question in (
        "把风扇打开，开玩笑的",
        "开风扇，算了还是不开了",
        "关风扇，逗你的",
        "把通风阈值调到20度，说着玩的",
    ):
        assert recognise(question).kind in (
            IntentKind.FAN_STATE,
            IntentKind.THRESHOLD_INFO,
        ), question


# -- typo normalisation, 2026-09-09 -------------------------------------------


def test_pinyin_misspellings_are_corrected_before_matching() -> None:
    """真人试用里"现在多少度"被打成"现在多少读"，规则整句落空。
    阀值不是手滑而是流传很广的误写（阀是阀门，该字是阈），打字时理直气壮，
    因此同样会撞上帮助文案。"""
    assert recognise("现在多少读").channel == TEMPERATURE_CHANNEL
    assert recognise("几读了").channel == TEMPERATURE_CHANNEL
    assert recognise("阀值是多少").kind is IntentKind.THRESHOLD_INFO
    assert recognise("噪声阀值多少").channel == NOISE_CHANNEL
    assert recognise("燥音多少").channel == NOISE_CHANNEL
    assert recognise("多少分被").channel == NOISE_CHANNEL


def test_correction_is_by_phrase_so_real_words_survive() -> None:
    """表按**词组**而非单字构建，正是为了这一组。
    "读"若单独映射成"度"，为修一个错字会毁掉"读数"——本系统天天用的词。
    表里每一条的左侧在中文中都不成词，改写因而无损。"""
    assert recognise("噪声读数是多少").channel == NOISE_CHANNEL
    assert recognise("温度读数多少").channel == TEMPERATURE_CHANNEL
    assert recognise("我在读书").kind is IntentKind.HELP


def test_normalise_leaves_well_typed_input_untouched() -> None:
    from service.assistant.intent import normalise

    for text in ("现在温度多少", "噪声读数", "阈值是多少", "风扇在转吗"):
        assert normalise(text) == text, text
    # 幂等：改过一遍再改不变
    assert normalise(normalise("多少读")) == normalise("多少读")


def test_bare_feeling_words_locate_the_channel() -> None:
    """"有点热呢"此前落空——词表有"太热""热吗"，唯独没有裸的"热"。
    风扇分支在通道分支之前，所以"太热了让那个吹风的转起来"仍是开风扇。"""
    for question in ("有点热呢", "好热啊", "热死了", "室温多少"):
        assert recognise(question).channel == TEMPERATURE_CHANNEL, question
    for question in ("有点潮", "好闷啊"):
        assert recognise(question).channel == HUMIDITY_CHANNEL, question
    assert recognise("太热了让那个吹风的转起来").kind is IntentKind.FAN_ON


def test_an_objectless_switch_command_is_asked_about_not_guessed() -> None:
    """"那你开开呗"没提风扇，规则整句落空。补法有两种：话题记忆（上句聊风扇
    就默认是风扇）或反问。取反问——记忆是悄悄猜，反问是明着问；两者代价同为
    一轮往返，只有后者可核对。"""
    for question in ("那你开开呗", "打开", "关了吧", "开一下", "停了"):
        assert recognise(question).kind is IntentKind.BARE_SWITCH, question


def test_naming_the_fan_or_a_channel_beats_the_bare_reading() -> None:
    """裸开关分支排在通道匹配之前，但要求句子里**没有**通道词；
    风扇分支又在它之前。两侧都点名了的句子照旧走原路。"""
    assert recognise("开风扇").kind is IntentKind.FAN_ON
    assert recognise("关掉风扇").kind is IntentKind.FAN_OFF
    assert recognise("打开的湿度是多少").channel == HUMIDITY_CHANNEL
    assert recognise("把通风阈值调到28").kind is IntentKind.SET_VENT_THRESHOLD
    assert recognise("关于噪声的阈值").kind is IntentKind.THRESHOLD_INFO


def test_a_question_about_yesterday_is_marked_as_out_of_range() -> None:
    """系统重启即丢数据（第 10 章已列为不足），"昨天最高多少"此前被答成
    **本次运行以来**的最高值。这是错误里最难发现的一种：每个数字都是真的，
    所以没有下游能拦——接地校验尤其拦不住，错的不是数字而是它所属的区间。"""
    for question in ("昨天温度最高多少", "这周平均温度", "今天噪声最高多少"):
        assert recognise(question).past_scoped is True, question


def test_a_question_about_last_year_is_marked_as_out_of_range() -> None:
    """2026-09-25 边界题库："去年夏天最高温度多少"被答成"监测到的最高温度是 40.0℃"，
    与上一条是同一种错——数是真的，区间是错的——只是词表里没有按年说的过去。
    "今年"与"今天"同类：统计量要加说明（今年的最高值可能在启动之前），当前读数不加。"""
    for question in ("去年夏天最高温度多少", "前年平均湿度多少", "去年温度多少",
                     "今年噪声最高多少"):
        assert recognise(question).past_scoped is True, question
    assert recognise("今年温度多少").past_scoped is False


def test_within_run_time_words_are_not_flagged() -> None:
    """"刚才""这一阵子""平时"指的正是这份数据覆盖的区间，不该加说明。"""
    for question in ("刚才最吵多少", "这一阵子平均多少度", "平时湿度大概多少"):
        assert recognise(question).past_scoped is False, question


def test_today_does_not_flag_a_question_about_the_current_reading() -> None:
    """2026-09-14 用户实测："今天天气不挺好的 咋地铁站这么热啊 现在是不是都快30度了"
    被答成"系统只保留本次运行以来的数据……当前温度为 25.9℃"。"今天"对统计量
    有意义（今天的最高值可能在启动之前），对当前读数没有——当前读数哪天问都是它。"""
    for question in (
        "今天天气不挺好的 咋地铁站这么热啊 现在是不是都快30度了",
        "今天温度多少",
        "这周噪声现在多大",
    ):
        intent = recognise(question)
        assert intent.kind is IntentKind.CURRENT_VALUE, question
        assert intent.past_scoped is False, question
    assert recognise("昨天温度多少").past_scoped is True
    assert recognise("今天噪声最高多少").past_scoped is True


def test_colloquial_noise_words_reach_the_noise_channel() -> None:
    """"这半天里最闹腾的时候"曾被答成温度：闹腾不在噪声词表里，通道落空，
    于是通道记忆用上一轮的温度补了位——一个没有任何迹象的错数。
    记忆的护栏（只补给已匹配到统计词的句子）在这里帮不上忙，因为"最闹"
    正是统计词。词表缺口只能靠补词表堵。"""
    for question in ("这半天里最闹腾的时候", "吵闹吗", "最闹腾的时候多少"):
        assert recognise(question, default_channel=TEMPERATURE_CHANNEL).channel == (
            NOISE_CHANNEL
        ), question


def test_asking_for_capabilities_is_narrower_than_landing_in_help() -> None:
    """两件事共用 HELP 这一个标签，判据却必须不同。

    2026-09-09 加占位答复时，我拿 `_HELP_WORDS` 判断"用户是不是在问能力"，
    问到能力就直接回清单、不叫模型。那张表里是**片段**——「你能」出现在
    「你能告诉我现在温度多少吗」里同样命中，于是这句正经问句变成了一次
    能力介绍，而且模型全程没被叫。这正是占位答复要消灭的死角，
    却被在它前面新开了一个。

    判错的代价不对称：分类判宽了，句子落到 HELP 还能由模型救回来；
    这里判宽了，一整类问句永远得不到回答。"""
    from service.assistant.intent import asks_for_help

    capability = ("你能干什么", "会做什么", "有什么功能", "能问什么", "帮助", "怎么用")
    for question in capability:
        assert asks_for_help(question) is True, question

    for question in (
        "你能告诉我现在温度多少吗",
        "你能看看噪声吗",
        "帮助我查一下湿度",
        "这个怎么用温度传感器",
        "你能把风扇打开吗",
    ):
        assert asks_for_help(question) is False, question


def test_asking_what_may_be_asked_gets_the_list() -> None:
    """2026-09-14 用户实测："我可以问你什么问题"被答成"温度现在是 26.3℃"。

    表里有"可以问什么"，原话中间多了个"你"，没命中，于是交给模型分类；
    模型偶尔照着提示词第一个例子回 current_value temperature，温度就这么编了出来。
    补的是**整句问能力的说法**，不是片段——带通道的问句仍须交出去。"""
    from service.assistant.intent import asks_for_help

    for question in (
        "我可以问你什么问题",
        "我能问你些什么",
        "你都能回答哪些问题",
        "能回答什么",
        "我可以问哪些",
    ):
        assert asks_for_help(question) is True, question
    for question in ("我可以问你一下温度多少吗", "问你个问题风扇开着吗"):
        assert asks_for_help(question) is False, question


# -- 上云提议（2026-09-18） ---------------------------------------------------


def test_a_request_to_upload_is_recognised() -> None:
    for question in ("把数据传上去", "上传一下归档", "同步到云端", "传上云"):
        assert recognise(question).kind is IntentKind.CLOUD_SYNC_HINT, question


def test_syncing_between_phone_and_desktop_is_not_an_upload_request() -> None:
    """词表刻意不收单字「同步」——"手机跟电脑同步吗"问的是网关，不是上云。
    每一条要么明说「云」，要么是在本系统里只有一个意思的「上传」。"""
    assert recognise("手机跟电脑同步吗").kind is not IntentKind.CLOUD_SYNC_HINT


def test_deleting_wins_over_uploading_when_a_sentence_says_both() -> None:
    """"把云上的数据删了"两样都提到了。判成删除，因为两个方向的代价不对称：
    把上云读丢，代价是用户再说一句；把删除读成上云，按钮就摆到它下面了。"""
    assert recognise("把云上的数据删了").kind is IntentKind.DELETE_REQUEST
    assert recognise("删掉已经上传的文件").kind is IntentKind.DELETE_REQUEST


def test_uploading_is_not_in_the_control_whitelist() -> None:
    """与删除同样三条准入性质全不满足。区别只在**动作是增量的**——
    早传上去的文件没有损失，早删掉的行没了。所以一个给按钮、一个给拒绝。"""
    from service.assistant.control import CONTROL_KINDS

    assert IntentKind.CLOUD_SYNC_HINT not in CONTROL_KINDS


# -- 查看云端归档（2026-09-19） -----------------------------------------------


def test_a_request_to_look_at_the_archive_is_recognised() -> None:
    for question in ("云上有什么", "云端有哪些文件", "看看云上传了什么",
                     "传上去的文件在哪", "打开控制台看看"):
        assert recognise(question).kind is IntentKind.CLOUD_VIEW_HINT, question


def test_looking_wins_over_uploading_when_a_sentence_says_both() -> None:
    """"把传上去的文件看一下"两边都沾，问的是看不是再传一次。
    读错方向最多少看一眼；反过来则是把一个外部动作摆到用户面前。"""
    assert recognise("把传上去的文件看一下").kind is IntentKind.CLOUD_VIEW_HINT


def test_a_bare_cloud_word_is_not_a_view_request() -> None:
    """词表用的是长短语而不是单个「云」：「云端只存不算吗」问的是设计。"""
    assert recognise("云端只存不算吗").kind is not IntentKind.CLOUD_VIEW_HINT
    assert recognise("看看温度").kind is not IntentKind.CLOUD_VIEW_HINT


def test_viewing_is_not_in_the_control_whitelist() -> None:
    """只读也不进白名单——准入判的是"该不该由助手发起一个子进程"，
    不是"这个动作有多危险"。"""
    from service.assistant.control import CONTROL_KINDS

    assert IntentKind.CLOUD_VIEW_HINT not in CONTROL_KINDS
