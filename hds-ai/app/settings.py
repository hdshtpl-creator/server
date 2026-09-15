"""
settings.py — Cài đặt hệ thống lưu trong CSDL, admin sửa được trên web.

Trước đây phong cách tư vấn (system prompt) và bản đồ thư mục Drive nằm cứng
trong mã nguồn → muốn đổi phải sửa code rồi khởi động lại. Nay lưu ở bảng
`app_settings`: admin đổi trên giao diện, có hiệu lực ngay câu hỏi tiếp theo.

Đọc: get(key) / get_json(key) / get_prompt(channel)
Ghi: set(key, value, user_id)  — chỉ admin, kiểm ở tầng API.
"""
import json
import os
import threading
import time

from app import db

# ---------------------------------------------------------------
# Giá trị mặc định. Chỉ dùng khi CSDL chưa có bản ghi tương ứng —
# nghĩa là admin sửa trên web thì bản DB luôn thắng.
# ---------------------------------------------------------------
DEFAULTS = {
    # Phong cách tư vấn cho 4 kênh chat (kênh thứ tư là tab Kiểm tra pháp lý)
    "prompt_public": (
        "Bạn là trợ lý của Công ty Luật HDS, trả lời khách trên website. "
        "Chỉ dựa vào TÀI LIỆU THAM KHẢO bên dưới. "
        "Trả lời NGẮN GỌN, khái quát, đúng trọng tâm. Nếu câu hỏi chưa rõ, "
        "hỏi lại một câu ngắn để làm rõ thay vì đoán. Không đủ căn cứ thì nói rõ. "
        "Không bịa điều luật, không nêu số hiệu văn bản nếu không có trong tài liệu. "
        "Có dẫn luật thì dẫn đủ tên văn bản + số hiệu + điều/khoản đúng như tài "
        "liệu ghi, không dẫn trống không kiểu 'theo quy định pháp luật'. "
        "Không kết luận chắc chắn về một vụ việc cụ thể qua website — đây là "
        "thông tin tham khảo, không phải ý kiến pháp lý chính thức. "
        "Kết thúc bằng gợi ý liên hệ luật sư HDS."
    ),
    "prompt_internal": (
        "Bạn là trợ lý pháp lý của HDS Law Firm — trò chuyện TỰ NHIÊN, THÂN "
        "THIỆN và chủ động như một đồng nghiệp giỏi, KHÔNG trả lời cộc lốc hay "
        "máy móc. Xưng 'mình'/'tôi' với người hỏi cho gần gũi. "
        "Dựa trên TÀI LIỆU THAM KHẢO và DỮ LIỆU CÔNG TY bên dưới để trả lời. "
        "LUÔN đọc DIỄN BIẾN CUỘC TRAO ĐỔI TRƯỚC ĐÓ để hiểu câu nối tiếp; nếu "
        "người dùng nói lại cho rõ (vd 'ý tôi là…', 'tôi hỏi X mà'), hiểu là "
        "đang chỉnh lại câu trước rồi trả lời luôn, đừng hỏi lại từ đầu. "
        "Trả lời rõ ràng, đủ ý, mạch lạc — trình bày dễ đọc (gạch đầu dòng khi "
        "cần) nhưng không lan man, không liệt kê máy móc mọi thứ dính từ khoá. "
        "Có ngày tháng/thời hạn thì tự so với HÔM NAY ở đầu prompt để biết còn "
        "hạn hay đã hết. "
        "NGUỒN SỰ THẬT: khi hỏi về nhân sự (bao nhiêu người, gồm những ai, chức "
        "danh, thời hạn hợp đồng), hãy trả lời theo HỒ SƠ NHÂN SỰ và HỢP ĐỒNG "
        "LAO ĐỘNG trong tài liệu — nêu rõ họ tên, chức danh, thời hạn của TỪNG "
        "người. Số tài khoản đăng nhập KHÔNG phải quân số công ty, chỉ nhắc tới "
        "khi được hỏi riêng về tài khoản phần mềm. "
        "Nếu dữ liệu chưa có thứ người dùng cần, nói thẳng một "
        "cách nhẹ nhàng và gợi ý bước tiếp theo (tìm ở đâu, cần bổ sung gì) — "
        "TUYỆT ĐỐI không bịa số liệu hay điều luật. Chỉ hỏi lại khi câu hỏi thật "
        "sự mơ hồ mà lịch sử cũng không giúp làm rõ.\n"
        "CÁCH DẪN CĂN CỨ PHÁP LÝ (bắt buộc, đây là chuẩn hành nghề):\n"
        "- Dẫn ĐẦY ĐỦ: tên loại văn bản + số hiệu + điều/khoản/điểm. Viết "
        "'khoản 2 Điều 35 Bộ luật Lao động số 45/2019/QH14', KHÔNG viết trống "
        "không 'theo Điều 35' hay 'theo quy định pháp luật'.\n"
        "- Số hiệu và số điều phải LẤY NGUYÊN từ tài liệu. Không nhớ chính xác "
        "thì dẫn đúng phần đọc được và nói rõ phần còn thiếu, tuyệt đối không "
        "suy ra số hiệu hay số điều.\n"
        "- Mỗi căn cứ kèm [Nguồn n] trỏ đúng đoạn đã dùng.\n"
        "- Văn bản có hiệu lực theo thời gian: nếu tài liệu ghi ngày hiệu lực, "
        "ngày hết hiệu lực hoặc văn bản thay thế, nêu rõ. Nếu không rõ văn bản "
        "còn hiệu lực hay đã bị thay thế, nói thẳng là cần kiểm tra lại hiệu "
        "lực — đừng khẳng định chắc chắn.\n"
        "- Có nhiều văn bản cùng điều chỉnh thì nêu thứ bậc (luật > nghị định > "
        "thông tư) và văn bản chuyên ngành ưu tiên áp dụng.\n"
        "CÁCH TRẢ LỜI CÂU HỎI PHÁP LÝ: trả lời thẳng kết luận trước, rồi tới "
        "căn cứ, rồi tới lưu ý/rủi ro thực tiễn nếu có. Khi câu hỏi có nhiều "
        "cách hiểu về mặt pháp lý, nêu cách hiểu chính và nói rõ điểm còn tranh "
        "luận. Đây là bản nháp tham khảo; luật sư chịu trách nhiệm cuối cùng.\n"
        "PHẢN BÁC TIỀN ĐỀ SAI (bắt buộc): câu hỏi có thể chứa căn cứ KHÔNG CÓ "
        "THẬT — sai số điều, sai tên văn bản, hoặc một văn bản không tồn tại. "
        "Trước khi trả lời, đối chiếu mốc pháp lý người hỏi nêu với TÀI LIỆU "
        "THAM KHẢO. Không tìm thấy thì NÓI THẲNG là chưa đối chiếu được và "
        "KHÔNG diễn giải nội dung cho nó; tuyệt đối không sáng tác quy định "
        "cho một điều luật chỉ vì người hỏi nhắc tới nó. Nếu biết chắc mốc đó "
        "sai (vd văn bản chỉ có tới Điều 220 mà người hỏi nêu Điều 500), chỉ "
        "ra chỗ sai rồi mới trả lời phần đúng của câu hỏi.\n"
        "NGƯỜI DÙNG SỬA LẠI CĂN CỨ: khi họ dán điều luật vào chat hoặc bảo "
        "trích dẫn của bạn sai, nguồn [Người dùng cung cấp trong hội thoại] là "
        "căn cứ ĐÁNG TIN NHẤT của lượt này. Trả lời lại theo nó và nói rõ đã "
        "sửa chỗ nào — tuyệt đối không lặp lại câu trả lời cũ.\n"
        "THIẾU DỮ KIỆN: tình huống thiếu dữ kiện để kết luận chắc chắn thì vẫn "
        "phân tích phần trả lời được, nêu kết luận theo từng khả năng, rồi "
        "KẾT THÚC bằng mục 'Cần bổ sung để kết luận chắc chắn:' liệt kê 2-4 "
        "câu hỏi cụ thể. Đừng khẳng định chắc nịch trên dữ liệu chưa đủ, cũng "
        "đừng từ chối trả lời chỉ vì thiếu vài chi tiết."
    ),
    "prompt_portal": (
        "Bạn là trợ lý của HDS phục vụ khách hàng đã ký hợp đồng. "
        "Chỉ dùng TÀI LIỆU THAM KHẢO thuộc về khách đang đăng nhập — không nhắc "
        "tới bất kỳ khách hàng nào khác. Trả lời NGẮN GỌN, dễ hiểu, đúng trọng "
        "tâm. Nếu câu hỏi chưa rõ, hỏi lại một câu để làm rõ. Không đủ căn cứ "
        "trong tài liệu thì nói rõ và đề nghị liên hệ luật sư phụ trách. "
        "Khi dẫn luật, dẫn đủ tên văn bản + số hiệu + điều/khoản đúng như tài "
        "liệu ghi, kèm [Nguồn n]."
    ),
    # Kênh nội bộ, chế độ "Kiểm tra pháp lý": người dùng tải hồ sơ khách gửi
    # lên khung chat rồi yêu cầu soi đúng/sai. Khác prompt_internal ở chỗ vai
    # trò là NGƯỜI RÀ SOÁT: đối chiếu từng điểm của hồ sơ với căn cứ trong kho
    # (luật, án lệ, bản án, quan điểm pháp lý) và kết luận rõ ràng theo từng
    # điểm, không tư vấn chung chung.
    "prompt_legal_review": (
        "Bạn là luật sư rà soát của Công ty Luật TNHH HDS. Nhiệm vụ: đối chiếu "
        "HỒ SƠ người dùng cung cấp (file đính kèm trong hội thoại) với căn cứ "
        "pháp lý trong TÀI LIỆU THAM KHẢO — văn bản luật, án lệ, bản án, quan "
        "điểm pháp lý và vụ việc tương tự HDS đã xử lý.\n"
        "Cách trình bày:\n"
        "1. TÓM TẮT HỒ SƠ: hồ sơ nói về việc gì, các bên là ai (1-3 câu).\n"
        "2. PHÂN TÍCH TỪNG ĐIỂM: mỗi điểm nêu rõ nội dung trong hồ sơ, căn cứ "
        "pháp lý đối chiếu (dẫn đủ tên văn bản + số hiệu + Điều/Khoản đúng như "
        "tài liệu ghi), và kết luận một trong ba mức: ĐÚNG QUY ĐỊNH / CẦN LƯU Ý "
        "/ TRÁI QUY ĐỊNH — kèm giải thích ngắn.\n"
        "3. RỦI RO & KHUYẾN NGHỊ: liệt kê rủi ro chính và việc nên làm.\n"
        "Mỗi nhận định dựa trên tài liệu phải kèm [Nguồn n]. Điểm nào kho chưa "
        "có căn cứ thì ghi rõ là chưa đủ căn cứ để kết luận, không suy đoán. "
        "Người chịu trách nhiệm cuối cùng là luật sư phụ trách — bài phân tích "
        "này là bản rà soát hỗ trợ."
    ),
    # Kênh nội bộ, chế độ "Đối chiếu với mẫu": nhân viên đính kèm file mình
    # soạn và chọn một mẫu trong kệ mẫu; model so từng mục (Nhi, 29/08/2026:
    # "kiểm tra biểu mẫu của nhân viên khi up lên có đúng mẫu quy định của
    # công ty không"). Mẫu vào nguồn với tiêu đề [Mẫu công ty: …].
    "prompt_template_check": (
        "Bạn là chuyên viên rà soát biểu mẫu của Công ty Luật TNHH HDS. Nhiệm vụ: "
        "đối chiếu FILE nhân viên đính kèm trong hội thoại với MẪU CÔNG TY (nguồn "
        "có tiêu đề [Mẫu công ty: …]) và chỉ ra chỗ lệch.\n"
        "Cách trình bày:\n"
        "1. MẪU YÊU CẦU GÌ: liệt kê các mục/điều khoản của mẫu theo đúng thứ tự, "
        "mỗi mục một dòng.\n"
        "2. BẢNG ĐỐI CHIẾU: cột Mục | Trong mẫu | Trong file | Kết luận; kết luận "
        "là ĐỦ / THIẾU / KHÁC MẪU / CẦN XEM LẠI — mỗi dòng dẫn [Nguồn n] của mẫu "
        "và của file.\n"
        "3. LỖI THỂ THỨC: thiếu quốc hiệu, số/ký hiệu, ngày, căn cứ, chữ ký, con "
        "dấu, đánh số điều… nếu có.\n"
        "4. VIỆC CẦN SỬA: theo thứ tự ưu tiên, nói rõ sửa thành gì theo mẫu.\n"
        "Chỉ kết luận trên nội dung hai tài liệu; không suy đoán nội dung không "
        "có. Không có file đính kèm thì chỉ làm mục 1 và nói rõ cần đính kèm file "
        "để đối chiếu."
    ),
    # Tham số sinh câu trả lời
    "llm_temperature": "0.2",
    # ---- Chính sách 20/08/2026: BOT KHÔNG BỊ GIỚI HẠN --------------------
    # Yêu cầu trực tiếp của chủ dự án: bot đọc HẾT mọi đoạn liên quan, không
    # cắt nội dung; chấp nhận chậm, chậm/lỗi xử lý sau. Giá trị 0 ở hai ngân
    # sách ký tự nghĩa là KHÔNG CẮT. Trần vật lý duy nhất là llm_num_ctx.
    # Máy đuối thì hạ các số này ngay trên web, có hiệu lực tức thì.
    "retrieval_top_k": "24",         # số đoạn tài liệu đưa vào prompt
    "retrieval_candidate_k": "300",  # hybrid search lấy rất rộng trước khi rerank
    "retrieval_max_chunks_per_doc": "8", # đa dạng nguồn, tránh một file chiếm hết
    "chunk_char_limit": "0",         # 0 = giữ TRỌN từng đoạn, không cắt
    "context_char_budget": "0",      # 0 = KHÔNG trần tổng tài liệu tham khảo
    "min_relevance": "0.25",         # vẫn lọc LIÊN QUAN — dưới ngưỡng là rác
    "strict_grounding": "true",       # không citation hợp lệ thì chặn câu tài liệu
    # Cửa sổ ngữ cảnh của model — TRẦN VẬT LÝ duy nhất còn lại. Prompt dài hơn
    # mức này bị Ollama cắt mất phần ĐẦU (đúng chỗ đặt DỮ LIỆU CÔNG TY), nên
    # đã nâng kịch cỡ context gốc của qwen3:14b. Máy thiếu RAM cho KV-cache
    # thì hạ 24576/16384 tại đây.
    "llm_num_ctx": "32768",
    # -1 = KHÔNG chặn độ dài câu trả lời (chính sách 20/08/2026 — không chặt
    # cụt); độ gọn giao cho lượt "bot đọc lại" (answer_review). Đặt số dương
    # khi cần ép trần thời gian trên máy quá yếu.
    "llm_num_predict": "-1",
    # Bot ĐỌC LẠI câu trả lời: auto = chỉ khi có dấu hiệu chưa ổn (quá dài,
    # bỏ lửng, lặp); always = mọi câu (chậm gấp đôi trên CPU); off = tắt.
    "answer_review": "auto",
    # BỘ NHỚ DÀI của hội thoại (cơ chế Claude/ChatGPT): hội thoại vượt số lượt
    # nhớ nguyên văn thì phần cũ được LLM cô đọng thành bản tóm tắt, chạy Ở
    # LUỒNG NỀN sau khi đã trả lời — không cộng thêm thời gian chờ. Nhờ vậy mở
    # lại chat cũ dài bao nhiêu bot vẫn nắm được tên khách, số hợp đồng, kết
    # luận đã chốt từ những lượt đầu.
    "history_summary_enabled": "true",
    # Trần độ dài bản tóm tắt (ký tự). To hơn = nhớ chi tiết hơn nhưng mỗi câu
    # hỏi tốn thêm bấy nhiêu ký tự prompt.
    "history_summary_max_chars": "2500",
    # Số luồng CPU cho model. 0 = để Ollama tự quyết (đúng cho máy có GPU).
    # Máy chạy CPU đôi khi nhanh hơn khi khai đúng số nhân — thử rồi đo lại.
    "llm_num_thread": "0",
    # Số lượt hỏi-đáp cũ đưa lại vào ngữ cảnh để bot hiểu "vụ đó", "khách kia".
    # Đặt 0 là tắt bộ nhớ hội thoại (mỗi câu hỏi độc lập).
    # 21/08/2026: chủ dự án yêu cầu bot nhớ dài — 10 lượt hỏi-đáp gần nhất kèm
    # theo mỗi câu hỏi mới (trước là 3). Mỗi message trong lịch sử được giữ tới
    # HISTORY_CHARS ký tự; hội thoại toàn câu trả lời rất dài mà chạm trần
    # num_ctx thì hạ số này trên web trước tiên.
    "chat_history_turns": "10",
    # Trần số file một lượt "Tạo bộ file" / điền bộ mẫu. 0 = KHÔNG giới hạn
    # (chủ dự án 15/09/2026). Mỗi file là một lời gọi model (~30-60 giây trên
    # GPU 16GB) — máy yếu hoặc dùng chung nhiều người thì đặt trần ở đây.
    "doc_factory_max_files": "0",
    # Kiểm tra mâu thuẫn pháp lý chạy NỀN sau mỗi lần lưu bản thảo (kế hoạch
    # ngày 9). 1 = bật. Mỗi lượt tốn ~1–3 phút model trên GPU; máy dùng chung
    # nhiều người thấy chậm thì đặt 0 và bấm "Kiểm tra lại" tay khi cần.
    "draft_check_auto": "1",
    # Model sinh câu trả lời (Ollama). Chính sách 20/08/2026: chạy FULL
    # qwen3:14b cho mọi câu — không tự hạ xuống model nhỏ. Admin đổi trên web
    # nếu máy không kham nổi. KHÔNG áp cho model tạo vector (bge-m3): mọi đoạn
    # đã lưu đều theo model đó, đổi là hỏng tra cứu.
    "llm_model": "qwen3:14b",
    # ---- NHÁNH GỌI API NGOÀI (Claude / Qwen qua API) --------------------
    # Mặc định TẮT. Bật là dữ liệu rời khỏi máy chủ HDS, nên đây phải là một
    # động tác có chủ ý của admin, không phải trạng thái mặc định.
    "cloud_enabled": "false",
    # Model dùng khi người hỏi chọn "Cloud" ở ô chat (giá trị 'cloud'). Tên
    # mang tiền tố nhà cung cấp: 'claude:<tên>' hoặc 'api:<tên>'.
    "cloud_model": "claude:claude-sonnet-5",
    # Kênh được phép gọi API, phân tách bằng dấu phẩy. KHÔNG mở cho 'public':
    # đó là cửa cho người lạ gõ câu hỏi không giới hạn — mở cloud ở đó là mở
    # hoá đơn cho người lạ bơm, dù đã có van chống spam theo IP.
    "cloud_channels": "internal",
    # Độ sâu suy nghĩ của model cloud: low | medium | high | xhigh | max.
    # Đây là NÚT CHỈNH CHI PHÍ chính sau khi đã chốt model — 'low' cho tra cứu
    # thường, 'high' khi rà soát hồ sơ.
    "cloud_effort": "medium",
    # Trần token model cloud được sinh ra. Khác llm_num_predict (=-1, không
    # chặn) vì API tính tiền theo token ra: không có trần là không có trần chi.
    "cloud_max_tokens": "8000",
    # API hỏng/hết quota giữa chừng thì tự quay về Ollama. Tắt cái này nghĩa là
    # chấp nhận mất câu trả lời khi mạng chập.
    "cloud_fallback_local": "true",
    # TRẦN KÝ TỰ TÀI LIỆU RIÊNG CHO NHÁNH CLOUD. Bắt buộc phải có: trên Ollama
    # num_ctx là trần vật lý, còn API thì KHÔNG CÓ trần nào — cửa sổ 1 triệu
    # token nghĩa là một câu hỏi có thể nuốt 2,6 triệu ký tự và vài đô la.
    # 60000 ký tự ≈ 23 nghìn token ≈ mức prompt hiện nay. Đặt 0 = theo cửa sổ
    # của model (ĐẮT, chỉ dùng khi đã hiểu mình đang trả tiền cho cái gì).
    "cloud_context_char_budget": "60000",
    # DỮ LIỆU NÀO ĐƯỢC PHÉP RỜI MÁY CHỦ. Câu hỏi chạm dữ liệu ngoài phạm vi
    # cho phép thì KHÔNG bị cắt xén — nó tự động quay về Qwen local. Nhờ vậy
    # không có đường nào rò dữ liệu mà cũng không có câu trả lời nào bị thiếu
    # căn cứ vì bộ lọc.
    #   law_only        — chỉ văn bản luật/án lệ/quan điểm KHÔNG gắn khách
    #                     hàng. Hồ sơ khách, dữ liệu công ty, file đính kèm
    #                     đều ở lại máy nhà. An toàn nhất.
    #   plus_attachments— thêm file người dùng TỰ đính kèm trong hội thoại
    #                     (đúng luồng tab Kiểm tra pháp lý). Kho hồ sơ khách
    #                     và dữ liệu công ty vẫn ở lại.
    #   all_but_finance — mọi thứ trừ công nợ/tài chính (chặn cứng, không cấu
    #                     hình gỡ được).
    "cloud_scope": "law_only",
    # NGUỒN VĂN BẢN TRÊN MẠNG cho bộ quét định kỳ (app/web_watch.py).
    # Mỗi nguồn tải file mới về một thư mục trong kho, rồi bộ quét kho học như
    # file nhân viên thả vào — nghĩa là vẫn qua cổng duyệt, vẫn phân quyền theo
    # tên thư mục. Mặc định KHÔNG có nguồn nào bật: đây là cửa duy nhất trong
    # hệ thống nhận dữ liệu từ Internet, phải là quyết định có chủ ý.
    #   kieu: rss | sitemap | html   (rss và sitemap dùng chung bộ đọc XML)
    #   mien_cho_phep: BẮT BUỘC — không có thì không tải gì, kể cả link trong
    #                  chính trang đó trỏ đi nơi khác.
    #   thu_muc: thư mục con trong kho → quyết định loại tài liệu và quyền xem
    #            (khớp với drive_map bên dưới).
    "web_sources": json.dumps(
        {
            "nguon": [
                {
                    "ten": "(mẫu — sửa url/miền rồi đặt bat=true)",
                    "bat": False,
                    "kieu": "rss",
                    "url": "https://vi-du.gov.vn/rss/van-ban-moi.xml",
                    "mien_cho_phep": ["vi-du.gov.vn"],
                    "thu_muc": "1. VĂN BẢN PHÁP LUẬT",
                    "duoi_file": [".pdf", ".doc", ".docx"],
                    "mau_lien_ket": "",
                    "toi_da_moi_lan": 20,
                }
            ]
        },
        ensure_ascii=False,
        indent=2,
    ),
    # Bản đồ thư mục Drive → nhãn tài liệu (app/auto_learn.py dùng).
    # Khoá được so khớp sau khi chuẩn hoá: bỏ số thứ tự đầu, bỏ dấu, viết thường.
    # Nhờ vậy "1. VĂN BẢN PHÁP LUẬT" và "van ban phap luat" là một.
    "drive_map": json.dumps(
        {
            "categories": {
                "văn bản pháp luật": {"doc_type": "law", "access_level": "public"},
                "bản án": {"doc_type": "ban_an", "access_level": "internal"},
                "án lệ": {"doc_type": "an_le", "access_level": "internal"},
                "bản án - án lệ": {"doc_type": "ban_an", "access_level": "internal"},
                "hợp đồng mẫu": {"doc_type": "mau_hd", "access_level": "internal"},
                "hợp đồng": {"doc_type": "contract", "access_level": "internal"},
                "quan điểm pháp lý": {"doc_type": "advisory", "access_level": "internal"},
                "thư tư vấn": {"doc_type": "advisory", "access_level": "internal"},
                "thư mẫu - biểu mẫu": {"doc_type": "thu_mau", "access_level": "internal"},
                "thư mẫu": {"doc_type": "thu_mau", "access_level": "internal"},
                "quy trình nội bộ": {"doc_type": "quy_trinh", "access_level": "internal"},
                "quy trình": {"doc_type": "quy_trinh", "access_level": "internal"},
                "nhãn hiệu - shtt": {"doc_type": "nhan_hieu", "access_level": "internal"},
                "nhãn hiệu": {"doc_type": "nhan_hieu", "access_level": "internal"},
                "hồ sơ nhân sự": {"doc_type": "ho_so_ns", "access_level": "internal"},
                "hồ sơ nộp cơ quan": {"doc_type": "filing", "access_level": "internal"},
                "tài liệu nội bộ": {"doc_type": "other", "access_level": "internal"},
                "nội bộ": {"doc_type": "other", "access_level": "internal"},
            },
            # Thư mục cấp 1 chứa hồ sơ khách hàng
            "client_roots": ["hồ sơ khách hàng", "khach hang", "khách hàng"],
            # Thư mục con trong hồ sơ khách → loại giấy tờ.
            # 'cong_no' là loại HẠN CHẾ: chặn ở CSDL (RLS), chỉ người được admin
            # cấp quyền xem tài chính mới tra cứu ra và bot mới dám nhắc tới.
            "client_subcategories": {
                "thông tin khách hàng": "ho_so_kh",
                "tổng hợp thông tin khách hàng": "ho_so_kh",
                "dự án": "ho_so_kh",
                "dự án - vụ việc": "ho_so_kh",
                "vụ việc": "ho_so_kh",
                "hợp đồng": "contract",
                "thư tư vấn": "advisory",
                "hồ sơ nộp cơ quan": "filing",
                "bản án": "ban_an",
                "công nợ": "cong_no",
                "công nợ - tài chính": "cong_no",
                "tài chính": "cong_no",
                # Quy ước thư mục DỰ ÁN thực tế của HDS (xem cây Drive tháng
                # 08/2026): mỗi vụ có 5 thư mục con cố định. Không map thì mọi
                # file rơi về ho_so_kh và khối "FILE TỔNG HỢP THÔNG TIN KHÁCH"
                # bị giấy ủy quyền/hướng dẫn ký chen mất chỗ của file tổng hợp
                # thật (xem company_context._client_lines ghim theo ho_so_kh).
                "tài liệu khách hàng cung cấp": "other",
                "hồ sơ soạn thảo": "filing",
                "hồ sơ hoàn thiện": "filing",
                "kết quả vụ việc": "filing",
                "hợp đồng dịch vụ": "contract",
            },
        },
        ensure_ascii=False,
        indent=2,
    ),
}

# Khoá được phép sửa qua API (chặn ghi khoá lạ)
EDITABLE_KEYS = set(DEFAULTS.keys())

# Model generation đọc nhiều tham số trong cùng một request. Trước đây mỗi lần
# `get_int()` lại mở một kết nối và SELECT riêng. Cache rất ngắn giữ cấu hình
# nhất quán trong một lượt chat; set/reset chủ động xoá cache nên thay đổi từ UI
# vẫn có hiệu lực ngay, không phải đợi TTL.
try:
    _CACHE_TTL = max(0.0, float(os.getenv("SETTINGS_CACHE_SECONDS", "2")))
except ValueError:
    _CACHE_TTL = 2.0
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE = None
_CACHE_AT = 0.0


def invalidate_cache():
    global _CACHE_VALUE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE_VALUE = None
        _CACHE_AT = 0.0


def get(key, default=None):
    """Đọc một cài đặt. Ưu tiên CSDL, không có thì lấy DEFAULTS."""
    return get_all().get(key, default)


def get_all():
    """Toàn bộ cài đặt hiện hành = DEFAULTS bị ghi đè bởi bản trong CSDL."""
    global _CACHE_VALUE, _CACHE_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if (_CACHE_VALUE is not None and _CACHE_TTL > 0
                and now - _CACHE_AT < _CACHE_TTL):
            return dict(_CACHE_VALUE)
    out = dict(DEFAULTS)
    try:
        with db.session(role="internal", admin=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM app_settings")
                for k, v in cur.fetchall():
                    out[k] = v
    except Exception:
        pass
    with _CACHE_LOCK:
        _CACHE_VALUE = dict(out)
        _CACHE_AT = time.monotonic()
    return dict(out)


def get_json(key):
    raw = get(key)
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def get_float(key, fallback):
    try:
        return float(get(key))
    except (TypeError, ValueError):
        return fallback


def get_int(key, fallback):
    try:
        return int(float(get(key)))
    except (TypeError, ValueError):
        return fallback


def get_prompt(channel):
    """Phong cách tư vấn theo kênh: public | internal | portal | legal_review."""
    return get(f"prompt_{channel}") or DEFAULTS.get(f"prompt_{channel}", "")


def set(key, value, user_id=None):  # noqa: A001 - đặt tên theo nghiệp vụ
    """Ghi một cài đặt. Kiểm quyền admin ở tầng API trước khi gọi."""
    if key not in EDITABLE_KEYS:
        raise ValueError(f"Khoá cài đặt không hợp lệ: {key}")
    if key in ("drive_map", "web_sources"):
        json.loads(value)  # sai JSON thì báo lỗi ngay, đừng để hỏng lúc quét kho
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_by, updated_at)
                   VALUES (%s,%s,%s,now())
                   ON CONFLICT (key) DO UPDATE
                     SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by,
                         updated_at=now()""",
                (key, value, user_id),
            )
        db.audit(conn, user_id, "update_setting", "app_settings", None, {"key": key})
    invalidate_cache()
    return True


def reset(key, user_id=None):
    """Xoá bản trong CSDL → quay về giá trị mặc định trong mã nguồn."""
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app_settings WHERE key=%s", (key,))
        db.audit(conn, user_id, "reset_setting", "app_settings", None, {"key": key})
    invalidate_cache()
    return DEFAULTS.get(key)


def set_system(key, value):
    """Ghi một giá trị hệ thống, KHÔNG qua kiểm tra EDITABLE_KEYS.

    Dùng cho các tiến trình nền tự ghi trạng thái của chính nó (vd auto_learn.py
    ghi 'drive_sync_status' sau mỗi lần quét) — khác với set(), vốn dành cho
    admin sửa tay qua API và phải nằm trong danh sách khoá được phép sửa.
    """
    with db.session(role="internal", admin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_at)
                   VALUES (%s,%s,now())
                   ON CONFLICT (key) DO UPDATE
                     SET value=EXCLUDED.value, updated_at=now()""",
                (key, value),
            )
    invalidate_cache()
