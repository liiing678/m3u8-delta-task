# HLS 增量播放列表恢复

## 起点与交付

基于仓库现有 Python m3u8 6.0.0 的解析器、M3U8/Segment/Key/PartialSegment 对象和 dumps 序列化扩展功能。上游能解析 SKIP，但没有恢复接口。主要工作位于 m3u8 包及其回归测试中，不能以旁路文本拼接程序取代库接口。实现与简短 API 使用说明一起交付；不要求播放器、网络下载器、解密或编解码。

增加公开接口 `m3u8.apply_delta(previous, update) -> M3U8`，两个参数均为当前库 `loads` 得到的 M3U8 对象；增加 `m3u8.DeltaUpdateError(ValueError)`，其 `reason` 为下述固定字符串之一。允许调整解析器保留新功能需要的上下文，现有 load/loads/parse/dumps 和上游测试必须兼容。测试对象在修改后的代码中重新解析，不要求兼容旧进程中已经丢失上下文的对象。

成功返回新的独立对象。成功和失败均不得修改两个输入的任何可观察状态。返回对象及其 data、segments、parts、keys、segment_map、init_section 等可变结构不能与输入共享；返回对象内部正常引用同一 key 是允许的。相同内容重复更新须语义幂等，不要求对象身份或序列化字节完全相同。

## 输入边界

这是单条 rendition 的媒体列表恢复，不处理主列表和多码率选择。调用方保证两个输入属于同一条 rendition。允许相对 URI；两个输入的 base_uri 必须相同（两者均为 None 也可），不支持跨基址迁移。对片段、KEY、MAP 的身份比较在有基址时使用解析后的 absolute_uri，无基址时使用原 URI 字符串。测试不要求查询参数改写、URL 网络访问或路径编码归一化。

previous 必须没有 SKIP。出现以下输入时抛 `DeltaUpdateError`，reason 为 `unsupported`：主列表、不同 base_uri、previous 含 SKIP、任一输入含 DATERANGE 或非空 RECENTLY-REMOVED-DATERANGES、非 identity 的 KEYFORMAT。支持无加密、METHOD=NONE 和 identity AES-128；不实际读取密钥。其他加密 METHOD 也返回 unsupported。本题不要求支持 SCTE-35 或自定义标签的新合并语义。

update 没有 SKIP 时代表全量替换：完成上述边界检查后返回独立副本，不继承 previous，不检查历史重叠。允许按输出一致性要求规范化状态及重建派生索引，不要求逐字段保留上游派生索引的瑕疵。SKIPPED-SEGMENTS=0 等同去掉 SKIP 后全量替换。负 SKIP 或接口可观察到的非整数为 `invalid-update`；loads 自身的解析异常仍保持原有语义。多个错误同时成立时不固定 reason 的优先级。以下窗口恢复规则针对正数 K 的 SKIP。

## 窗口与重叠

设 update.media_sequence=M、skipped_segments=K。update 中第 i 个完整片段的真实编号是 M+K+i，不能直接使用上游当前为 delta 对象生成的 segment.media_sequence。previous 中完整片段从 previous.media_sequence 依次编号。uri=None 且含 parts 的最后一项是未完成片段容器，占下一个编号，但不能作为被跳过的完整历史。

输出由 previous 中编号 [M,M+K) 的完整片段和 update 中显式列出的片段组成；不保留窗口之前的片段，不额外追加 previous 的尾部。输出 media_sequence=M，去除 SKIP，重建每个 segment.media_sequence。跳过区间任一编号无完整历史时 reason 为 `missing-history`。

同一编号在两边均为完整片段时，恢复上下文后的 URI、duration（允许误差 1e-6 秒）、实际 byte range、有效 KEY（method/uri/iv/keyformat/keyformatversions）、MAP（uri/byte range）、gap 标记和有效 discontinuity 序号必须一致，否则 reason 为 `conflict`。未设置 KEYFORMAT 与 identity 等同。KEY 的 IV 缺省与显式值不要求等价归一化。PDT 两边已知时须在 1 毫秒内一致。title 不参与冲突判断，以 update 为准。若恢复结果最后完整片段编号小于 previous 的最后完整片段编号，reason 为 `stale-update`；旧尾端未完成容器不用于该判定。其他非法片段形态（非尾端 uri=None、完整片段 duration 缺失/非正、负 media_sequence）返回 invalid-update。

## 需要恢复的上下文

KEY 与 MAP：恢复被跳过前缀的有效状态；update 首个显式声明之前沿用该前缀末尾的状态。无 KEY 标签是继承，METHOD=NONE 是清除加密且继续对后续片段生效。MAP 独立于 KEY 变化。保留 AES-128 显式 IV；无 IV 时仍通过正确 MSN 表达隐式 IV 的语义。

字节范围：支持完整片段 EXT-X-BYTERANGE 的 length@offset 和 length。隐式 offset 等于紧邻前一完整片段范围的末尾，且资源 URI 必须相同；没有可用前驱或资源不同则为 missing-history。恢复输出首片段的 offset 时可以读取被裁出窗口的 previous 前驱，但不得将其加入输出。MAP 及 PART 样本的范围均带显式 offset，不要求推导其隐式 offset。输出可把所有完整片段范围显式化，以确保脱离旧窗口仍可读取正确字节。

断点：每个完整片段的有效 discontinuity 序号等于列表 discontinuity_sequence（缺省 0）加截至该片段且包含它自身的 DISCONTINUITY 标记数。update.discontinuity_sequence 描述 M 前的计数。它应与 previous 对应窗口相符；不符为 conflict。输出保留恢复前缀和更新后缀的标记，不重复累计。此规则也适用于只有 PART 的尾端容器。

节目时间：支持带时区 PDT 和普通正时长。片段起点取显式 PDT；否则从已知前一完整片段起点加其 duration 推进。跨 DISCONTINUITY 不外推，必须由新显式 PDT 重新锚定，否则时间未知。裁剪首片段时，previous 中已有的推导时间仍须保留。PART 时间从所属片段起点逐项累计，其时长不得再叠加到完整片段时长上。当前上游的 PART/PDT 推导值可能已偏移；不得把这个偏移当作输入事实。比较及输出以显式锚点和上述规则为准。未知时间保持 None，不猜测墙钟时间。

PART：同一 MSN 的旧尾端容器在 update 出现完整片段时被其替换。update 所列 parts 是该 MSN 最新完整清单，不能与旧 parts 简单相加。完整片段携带 parts 时仅算一个完整片段时长；尾端容器不生成 EXTINF/URI。保留 PART 的 URI、duration、byterange、independent、gap。支持尾端前新的 KEY/MAP/DISCONTINUITY/PDT 声明，必要时补足解析器对此位置的状态保存。

## 输出一致性与检查

列表级 metadata（version、target_duration、server_control、part_inf、preload_hint、rendition_reports、endlist 等）以 update 为准，例外只有上面定义的恢复状态。keys、segment_map、files 和 data 须与恢复后的对象一致，不得仍只描述 delta 后缀。keys 和 segment_map 按出现顺序去重，包含输出中实际使用的状态；files 按首次出现顺序列出非空 key URI，再列出完整 segment URI（保留重复），不含 METHOD=NONE 或 PART-only 容器产生的 None。data 的字段结构沿用现有 parse 结果，使 `M3U8()` 设置 data 后 `_initialize_attributes()` 可重建同等语义。

`result.dumps(timespec="microseconds")` 再经 `loads(..., uri=同一播放列表地址)` 解析后，仍有相同窗口、完整与部分片段、有效 KEY/MAP/range/discontinuity/PDT 语义。可以增加为保持首片段上下文所必需的标签；不要求原文本标签顺序、空行或小数格式一致。输出不得含 SKIP，也不能把 preload hint 当已完成 PART。

task/fixtures 中是缩减的客户端状态恢复样本，不是实际节目或媒体数据；不模拟服务器选择 skip boundary 的过程，无需访问样本 .invalid 域名。task/test_delta_contract.py 提供可执行的公开检查，题目还要求补充边界测试。验收同时检查这些样本、上述公开边界和原有 tests 全集，不以新增测试绿灯代替实际序列化再解析。没有硬件性能阈值，不要求音视频解码，因为本题只恢复播放列表控制信息。

协议依据：RFC 8216 的媒体序号、KEY/MAP/BYTERANGE/PDT 语义，以及 HLS 二版工作草案 draft-pantos-hls-rfc8216bis-16 的 SKIP/PART 定义。这里只实现上面明确列出的范围及库 API 冲突处理策略，不宣称实现全部 HLS 标准。参考：https://www.rfc-editor.org/rfc/rfc8216 和 https://datatracker.ietf.org/doc/html/draft-pantos-hls-rfc8216bis-16 。执行所需规则已在本文件给出。
