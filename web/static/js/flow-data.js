/**
 * flow-data.js - 消息处理流水线数据定义（精简重构版）
 * 按实际代码执行顺序，将所有配置项映射到流水线各阶段各步骤
 * V2.0.1-lite：移除已删除功能（主动对话/私聊/注意力/等待窗口/情绪/拟人/疲劳/错字/打字/频率/质量/密度等）的节点
 */

const FlowData = {
    _nodeMap: {},   // stepId → 步骤对象
    _stageMap: {},  // stageId → 阶段对象

    pipelines: [
        {
            id: 'main',
            name: '消息处理流水线',
            icon: '💬',
            desc: '群消息从接入到回复的完整处理链路',
            stages: []
        }
    ],

    crossLinks: [],

    init() {
        this.pipelines[0].stages = this._mainStages();
        this._buildIndexes();
        return this;
    },

    _buildIndexes() {
        this._nodeMap = {};
        this._stageMap = {};
        for (const pipeline of this.pipelines) {
            for (const stage of pipeline.stages) {
                this._stageMap[stage.id] = stage;
                for (const step of stage.steps) {
                    this._nodeMap[step.id] = step;
                }
            }
        }
    },

    // ==================== 主流水线 ====================

    _mainStages() {
        return [
            this._stageEntry(),
            this._stageTrigger(),
            this._stageProbability(),
            this._stageContent(),
            this._stageAiDecision(),
            this._stageReplyGen(),
            this._stagePostReply()
        ];
    },

    /** Stage 1: 消息接入与预过滤 */
    _stageEntry() {
        return {
            id: 'entry',
            name: '消息接入与预过滤',
            icon: '🚪',
            desc: '群消息进入系统，逐步通过各项过滤器，任一环节不通过则丢弃消息',
            nextStage: 'trigger',
            nextLabel: '通过全部预过滤',
            steps: [
                {
                    id: 'enable-check',
                    name: '群聊总开关',
                    icon: '🔘',
                    desc: '检查群聊功能是否启用，以及当前群是否在启用列表中',
                    toggle: 'enable_group_chat',
                    keys: ['enable_group_chat', 'enabled_groups', 'enable_debug_log'],
                    onFail: 'drop',
                    failLabel: '未启用 → 忽略消息',
                    next: 'user-blacklist'
                },
                {
                    id: 'user-blacklist',
                    name: '用户黑名单',
                    icon: '🚫',
                    desc: '检查发送者是否在黑名单中',
                    toggle: 'enable_user_blacklist',
                    keys: ['enable_user_blacklist', 'blacklist_user_ids'],
                    onFail: 'drop',
                    failLabel: '黑名单用户 → 丢弃',
                    next: 'message-parse'
                },
                {
                    id: 'message-parse',
                    name: '特殊消息解析',
                    icon: '📋',
                    desc: '解析 QQ / OneBot 合并转发消息，并将结果折叠为单条 AI 可读文本',
                    activeIfAny: ['enable_forward_message_parsing'],
                    keys: ['enable_forward_message_parsing', 'forward_max_nesting_depth'],
                    onFail: 'pass',
                    next: 'at-filter'
                },
                {
                    id: 'at-filter',
                    name: '@消息过滤',
                    icon: '📢',
                    desc: '@全体成员与@他人采用相邻但独立的规则：可先忽略@全体成员；@他人过滤会基于完整提及结构判断，多人@、重复@同一人按统一结构处理；同时@AI时允许继续处理。通过过滤后，消息内部的At标签会被补足为可读形式（如 [At:123|张三]）。',
                    activeIfAny: ['enable_ignore_at_all', 'enable_ignore_at_others', 'at_all_message_mode'],
                    keys: ['enable_ignore_at_all', 'at_all_message_mode', 'enable_ignore_at_others'],
                    onFail: 'drop',
                    failLabel: '命中@过滤 → 丢弃',
                    next: 'poke-detect'
                },
                {
                    id: 'poke-detect',
                    name: '戳一戳检测',
                    icon: '👆',
                    desc: '检测戳一戳/拍一拍消息，决定处理方式和反戳概率',
                    keys: ['poke_message_mode', 'poke_reverse_on_poke_probability',
                           'poke_enabled_groups'],
                    onFail: 'drop',
                    failLabel: '戳一戳被忽略 → 丢弃',
                    next: 'cmd-filter'
                },
                {
                    id: 'cmd-filter',
                    name: '指令过滤',
                    icon: '⌨️',
                    desc: '识别指令前缀和完整指令，交给指令系统处理',
                    keys: ['enable_command_filter', 'command_prefixes',
                           'full_command_list', 'command_prefix_match_list',
                           'plugin_gcp_reset_allowed_user_ids',
                           'plugin_gcp_reset_here_allowed_user_ids'],
                    onFail: 'passthrough',
                    failLabel: '是指令 → 交给指令系统',
                    next: null
                }
            ]
        };
    },

    /** Stage 2: 触发检测 */
    _stageTrigger() {
        return {
            id: 'trigger',
            name: '触发检测',
            icon: '🎯',
            desc: '检测消息是否包含@、关键词等触发条件，决定后续处理方式',
            nextStage: 'probability',
            nextLabel: '进入概率判定',
            steps: [
                {
                    id: 'trigger-detect',
                    name: '触发条件检测',
                    icon: '🔍',
                    desc: '检测@消息、触发关键词、黑名单关键词',
                    activeIfAny: ['trigger_keywords'],
                    keys: ['trigger_keywords', 'keyword_smart_mode',
                           'blacklist_keywords'],
                    onFail: 'pass',
                    next: null
                }
            ]
        };
    },

    /** Stage 3: 概率判定系统 */
    _stageProbability() {
        return {
            id: 'probability',
            name: '概率判定系统',
            icon: '🎲',
            desc: '基础概率经修饰后随机判定是否回复（已移除注意力/时间段/疲劳/密度/质量/频率等修饰器）',
            nextStage: 'content',
            nextLabel: '概率通过',
            steps: [
                {
                    id: 'base-probability',
                    name: '基础概率',
                    icon: '📊',
                    desc: '初始概率值，回复后临时提升概率，戳一戳跳过概率检查；@全体成员可按专用模式跳过概率或仅临时提升当前消息概率',
                    keys: ['initial_probability', 'after_reply_probability',
                           'probability_duration', 'poke_bot_skip_probability',
                           'at_all_message_mode', 'at_all_probability_boost_value'],
                    onFail: 'pass',
                    next: 'hard-limit'
                },
                {
                    id: 'hard-limit',
                    name: '概率硬限',
                    icon: '🔒',
                    desc: '强制将最终概率钳位在用户设定的最小/最大范围内',
                    toggle: 'enable_probability_hard_limit',
                    keys: ['enable_probability_hard_limit',
                           'probability_min_limit', 'probability_max_limit'],
                    onFail: 'pass',
                    next: 'random-roll'
                },
                {
                    id: 'random-roll',
                    name: '随机判定',
                    icon: '🎰',
                    desc: '生成随机数与最终概率比较，决定是否继续处理',
                    internal: true,
                    keys: [],
                    onFail: 'drop',
                    failLabel: '概率未通过 → 缓存消息',
                    next: 'prob-cache'
                },
                {
                    id: 'prob-cache',
                    name: '概率过滤缓存',
                    icon: '💾',
                    desc: '概率未通过时，缓存消息文本（含图片描述提取）供后续上下文使用',
                    keys: ['probability_filter_cache_delay',
                           'platform_image_caption_max_wait',
                           'platform_image_caption_retry_interval',
                           'platform_image_caption_fast_check_count'],
                    onFail: 'pass',
                    next: null
                }
            ]
        };
    },

    /** Stage 4: 消息内容处理 */
    _stageContent() {
        return {
            id: 'content',
            name: '消息内容处理',
            icon: '📝',
            desc: '提取和处理消息原始内容，为AI理解做准备',
            nextStage: 'ai-decision',
            nextLabel: '内容处理完成',
            steps: [
                {
                    id: 'image-process',
                    name: '图片处理',
                    icon: '🖼️',
                    desc: '图片转文字(OCR)、多模态识别、平台描述提取、缓存管理',
                    toggle: 'enable_image_processing',
                    keys: ['enable_image_processing', 'image_to_text_scope',
                           'image_to_text_provider_id', 'image_to_text_prompt',
                           'image_to_text_timeout',
                           'enable_image_description_cache', 'image_description_cache_max_entries',
                           'gcp_clear_image_cache_allowed_user_ids'],
                    onFail: 'pass',
                    next: 'metadata-inject'
                },
                {
                    id: 'metadata-inject',
                    name: '元数据注入',
                    icon: '🏷️',
                    desc: '为消息添加时间戳和发送者信息，帮助AI理解对话上下文',
                    keys: ['include_timestamp', 'include_sender_info'],
                    onFail: 'pass',
                    next: 'context-build'
                },
                {
                    id: 'context-build',
                    name: '上下文构建',
                    icon: '📚',
                    desc: '组装历史消息上下文，控制消息数量和缓存策略',
                    keys: ['max_context_messages', 'pending_cache_max_count',
                           'pending_cache_ttl_seconds'],
                    onFail: 'pass',
                    next: null
                }
            ]
        };
    },

    /** Stage 5: AI决策判定 */
    _stageAiDecision() {
        return {
            id: 'ai-decision',
            name: 'AI决策判定',
            icon: '🧠',
            desc: '调用AI判断是否应该回复当前消息（读空气）',
            nextStage: 'reply-gen',
            nextLabel: 'AI判定回复',
            steps: [
                {
                    id: 'memory-inject',
                    name: '记忆注入',
                    icon: '🧠',
                    desc: '调用外部记忆插件（livingmemory），将长期记忆注入AI上下文',
                    toggle: 'enable_memory_injection',
                    keys: ['enable_memory_injection', 'memory_plugin_mode',
                           'livingmemory_version', 'livingmemory_persona_compat_mode',
                           'livingmemory_top_k', 'memory_insertion_timing'],
                    onFail: 'pass',
                    next: 'ai-decide'
                },
                {
                    id: 'ai-decide',
                    name: 'AI读空气决策',
                    icon: '💭',
                    desc: '调用决策AI分析对话上下文，判断是否适合回复。关键词命中只代表进入判断流程或获得提示，不代表必须回复。当前消息发送者仍然是读空气判断的主要对象',
                    promptDataKey: 'decision-ai',
                    keys: ['decision_ai_provider_id', 'decision_ai_include_persona',
                           'decision_ai_prompt_mode',
                           'decision_ai_extra_prompt', 'decision_ai_timeout'],
                    onFail: 'drop',
                    failLabel: 'AI判定不回复 → 缓存消息',
                    next: 'concurrent-lock'
                },
                {
                    id: 'concurrent-lock',
                    name: '并发锁定',
                    icon: '🔐',
                    desc: '防止同一群组同时处理多条消息导致重复回复。\n• legacy模式（默认）：等待旧消息处理完再处理新消息，每条消息独立回复\n• smart模式：将同期到达的新消息合并进当前处理上下文，AI一次性感知所有消息后回复，避免「明明说了还说」的重复感',
                    keys: ['concurrent_wait_max_loops', 'concurrent_wait_interval',
                           'concurrent_mode', 'smart_concurrent_merge_wait',
                           'smart_concurrent_max_batch_size'],
                    onFail: 'pass',
                    next: null
                }
            ]
        };
    },

    /** Stage 6: 回复生成 */
    _stageReplyGen() {
        return {
            id: 'reply-gen',
            name: '回复生成',
            icon: '✍️',
            desc: '注入记忆上下文，调用AI生成回复（只传人格+纯上下文，不注入任何行为指令），经过多重过滤后输出',
            nextStage: 'post-reply',
            nextLabel: '回复已发送',
            steps: [
                {
                    id: 'ai-reply-gen',
                    name: 'AI回复生成',
                    icon: '✨',
                    desc: '调用AI模型生成回复文本。system_prompt 只含人格设定，prompt 只含纯上下文+发送者标注，不注入任何行为指令',
                    promptDataKey: 'reply-ai',
                    keys: ['reply_ai_prompt_mode', 'reply_ai_extra_prompt'],
                    onFail: 'pass',
                    next: 'content-filter'
                },
                {
                    id: 'content-filter',
                    name: '内容过滤',
                    icon: '🧹',
                    desc: '过滤输出内容中的敏感词、保存过滤、重复消息拦截',
                    activeIfAny: ['enable_output_content_filter', 'enable_save_content_filter', 'enable_duplicate_filter'],
                    keys: ['enable_output_content_filter', 'output_content_filter_rules',
                           'enable_save_content_filter', 'save_content_filter_rules',
                           'enable_duplicate_filter', 'duplicate_filter_check_count',
                           'duplicate_filter_time_limit'],
                    onFail: 'drop',
                    failLabel: '内容被过滤 → 不发送',
                    next: null
                }
            ]
        };
    },

    /** Stage 7: 回复后处理 */
    _stagePostReply() {
        return {
            id: 'post-reply',
            name: '回复后处理',
            icon: '📤',
            desc: '回复发送后的状态更新、概率提升和附加动作',
            nextStage: null,
            nextLabel: null,
            steps: [
                {
                    id: 'history-save',
                    name: '历史保存',
                    icon: '💾',
                    desc: '将Bot回复保存到对话历史缓存',
                    internal: true,
                    keys: [],
                    onFail: 'pass',
                    next: 'prob-boost'
                },
                {
                    id: 'prob-boost',
                    name: '概率提升',
                    icon: '📈',
                    desc: '回复后临时提升对该群的回复概率（延续对话）',
                    internal: true,
                    keys: [],
                    onFail: 'pass',
                    next: 'poke-after-reply'
                },
                {
                    id: 'poke-after-reply',
                    name: '回复后戳一戳',
                    icon: '👆',
                    desc: '回复后按概率戳一戳发送者，增加互动感',
                    toggle: 'enable_poke_after_reply',
                    keys: ['enable_poke_after_reply', 'poke_after_reply_probability',
                           'poke_after_reply_delay',
                           'enable_poke_trace_prompt', 'poke_trace_max_tracked_users',
                           'poke_trace_ttl_seconds'],
                    onFail: 'pass',
                    next: null
                }
            ]
        };
    }
,

    // ==================== 查询方法（兼容 ConfigEditor / TechTree） ====================

    /** 根据 ID 获取步骤（节点）数据 */
    getNodeById(id) {
        return this._nodeMap[id] || null;
    },

    /** 根据 ID 获取阶段 */
    getStageById(id) {
        return this._stageMap[id] || null;
    },

    /** 根据 ID 获取流水线 */
    getPipelineById(id) {
        return this.pipelines.find(p => p.id === id) || null;
    },

    /** 获取步骤所属的阶段和流水线 */
    getStepContext(stepId) {
        for (const pipeline of this.pipelines) {
            for (const stage of pipeline.stages) {
                for (const step of stage.steps) {
                    if (step.id === stepId) {
                        return { step, stage, pipeline };
                    }
                }
            }
        }
        return null;
    },

    /** 获取所有步骤的扁平列表（兼容旧 getAllNodes） */
    getAllNodes() {
        const all = [];
        for (const pipeline of this.pipelines) {
            for (const stage of pipeline.stages) {
                for (const step of stage.steps) {
                    all.push({ ...step, stageId: stage.id, pipelineId: pipeline.id });
                }
            }
        }
        return all;
    },

    /** 根据配置key查找所属步骤（兼容旧 findNodeByKey） */
    findNodeByKey(key) {
        for (const pipeline of this.pipelines) {
            for (const stage of pipeline.stages) {
                for (const step of stage.steps) {
                    if (step.keys && step.keys.includes(key)) {
                        return { node: step, flow: { id: pipeline.id, name: pipeline.name } };
                    }
                }
            }
        }
        return null;
    }

};

// 初始化
FlowData.init();
