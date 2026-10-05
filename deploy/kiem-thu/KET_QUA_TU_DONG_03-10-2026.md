# KẾT QUẢ CHẠY TỰ ĐỘNG BỘ KIỂM THỬ — 03/10/2026

Chạy trên máy chủ thật (`127.0.0.1:8000`, bản `giao diện nt0310-0310.0149 · backend 03/10 04:53`) bằng bộ chạy `kiem-thu/nguon/` ↔ `/tmp/kt` — tài khoản thử riêng (đã khoá sau khi chạy), tài liệu chim mồi (đã gỡ). Kết quả chi tiết từng ca: `KET_QUA_TU_DONG_03-10-2026.xlsx`.

## 1. Tổng hợp

| | ĐẠT | KHÔNG ĐẠT | CHẶN | BỎ QUA | Tổng |
|---|---|---|---|---|---|
| Ca chức năng | 143 | 1 | 0 | 10 | 154 |

| 40 kịch bản HDS (máy chấm sơ bộ theo số Điều) | ĐÚNG 14 | MỘT PHẦN 9 | SAI 7 | luật sư chấm 10 | 40 |

*BỎ QUA* = ca thao tác giao diện (kiểm tay) hoặc hạng mục chưa bàn giao. *CHẶN* = không chạy được vì lỗi kỹ thuật khi test — xem cột Thực tế.

## 1b. So với lượt chạy trước (02/10/2026, trước đợt sửa)

| | ĐẠT | KHÔNG ĐẠT | CHẶN | BỎ QUA | Tổng |
|---|---|---|---|---|---|
| Lượt trước | 114 | 18 | 0 | 16 | 148 |
| Lượt này | 143 | 1 | 0 | 10 | 154 |

40 KB: lượt trước ĐÚNG 8 · MỘT PHẦN 13 · SAI 9 → lượt này ĐÚNG 14 · MỘT PHẦN 9 · SAI 7.

Ca đổi kết quả:

| Mã | Lượt trước | Lượt này |
|---|---|---|
| BM-07 | KHÔNG ĐẠT | ĐẠT |
| BM-08 | KHÔNG ĐẠT | ĐẠT |
| CH-01 | KHÔNG ĐẠT | ĐẠT |
| CH-05 | KHÔNG ĐẠT | ĐẠT |
| CH-12 | KHÔNG ĐẠT | ĐẠT |
| CH-13 | KHÔNG ĐẠT | ĐẠT |
| CHUA-01 | BỎ QUA | ĐẠT |
| CHUA-03 | BỎ QUA | ĐẠT |
| CHUA-06 | BỎ QUA | ĐẠT |
| CHUA-07 | BỎ QUA | ĐẠT |
| DN-07 | (ca mới) | ĐẠT |
| HT-04 | KHÔNG ĐẠT | ĐẠT |
| HT-05 | KHÔNG ĐẠT | ĐẠT |
| KHO-11 | (ca mới) | ĐẠT |
| KT-07 | KHÔNG ĐẠT | ĐẠT |
| PNF-01 | KHÔNG ĐẠT | ĐẠT |
| PNF-04 | KHÔNG ĐẠT | ĐẠT |
| PQ-12 | (ca mới) | ĐẠT |
| PQ-13 | (ca mới) | ĐẠT |
| ST-04 | BỎ QUA | ĐẠT |
| ST-07 | KHÔNG ĐẠT | ĐẠT |
| TH-02 | KHÔNG ĐẠT | ĐẠT |
| TH-03 | KHÔNG ĐẠT | ĐẠT |
| TH-04 | KHÔNG ĐẠT | ĐẠT |
| TH-06 | (ca mới) | ĐẠT |
| TK-08 | KHÔNG ĐẠT | ĐẠT |
| TK-13 | (ca mới) | ĐẠT |
| WEB-06 | KHÔNG ĐẠT | ĐẠT |
| WEB-08 | BỎ QUA | ĐẠT |

KB đổi kết quả:

| KB | Lượt trước | Lượt này |
|---|---|---|
| 1.1 | MỘT PHẦN | ĐÚNG |
| 1.3 | SAI | ĐÚNG |
| 1.4 | SAI | ĐÚNG |
| 1.10 | MỘT PHẦN | ĐÚNG |
| 2.2 | SAI | ĐÚNG |
| 2.6 | MỘT PHẦN | ĐÚNG |
| 2.8 | MỘT PHẦN | SAI |
| 4.6 | SAI | MỘT PHẦN |
| 4.9 | MỘT PHẦN | SAI |

## 2. Ca KHÔNG ĐẠT

| Mã | Thực tế quan sát |
|---|---|
| BM-04 | 200 AI đoán=[] nguồn tờ khai=['gõ tay trên giao diện'] |

## 3. Ca CHẶN (lỗi kỹ thuật khi chạy test)

| Mã | Lỗi |
|---|---|

## 4. 40 kịch bản pháp lý — máy chấm sơ bộ

Máy chỉ đếm **số Điều** và **tên văn bản** trong câu trả lời so với cột *Phải dẫn*; luật sư HDS chấm lại nội dung ở sheet *Trả lời 40 KB (toàn văn)*. Kho dùng bản luật mới nhất nên số điều có thể lệch bản 2020 của tiêu chí.

| KB | Máy chấm | Giây | Kiểm chứng | Điều bot dẫn | Lý do |
|---|---|---|---|---|---|
| 1.1 | ĐÚNG | 102.6 | verified | 1, 15, 24, 35, 36, 47, 50, 75, 140, 187 | đủ Điều [35, 47], văn bản ['LDN'] |
| 1.2 | ĐÚNG | 133.3 | partial | 3, 26, 44, 74 | đủ Điều [26], văn bản ['Luật Đầu tư'] |
| 1.3 | ĐÚNG | 61.9 | partial | 24, 78, 81, 82, 116, 117 | đủ Điều [117], văn bản ['LDN'] |
| 1.4 | ĐÚNG | 65.6 | partial | 45, 46 | đủ Điều [46], văn bản ['Luật Đầu tư', 'Luật Đất đai'] |
| 1.5 | ĐÚNG | 93.1 | verified | 8, 9, 28, 154, 202, 203, 204, 205 | đủ Điều [202], văn bản ['LDN'] |
| 1.6 | MỘT PHẦN | 69.6 | partial | 3, 140, 688 | dẫn [3]/[3, 127], thiếu [127]; văn bản ['LDN', 'BLDS'] |
| 1.7 | BỎ QUA | 91.5 | partial | 13, 16, 20, 26 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí ([]); Điều dẫn [13, 16, 20, 26]) |
| 1.8 | SAI | 52.4 | verified | 55, 95, 113, 125, 135, 212 | không dẫn Điều nào trong [51]; Điều bot dẫn [55, 95, 113, 125, 135, 212]; văn bản ['LDN'] |
| 1.9 | BỎ QUA | 104.4 | verified | 5, 6, 7, 8, 13, 15, 16 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không có số Điều tiêu chí; dẫn văn bản ['NHNN'], Điều [5, 6, 7, 8, 13, 15, 16] |
| 1.10 | ĐÚNG | 104.0 | verified | 33, 49, 68, 112 | đủ Điều [68, 112], văn bản ['LDN'] |
| 2.1 | BỎ QUA | 48.1 | verified | 5, 7, 16, 18, 171, 172 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí (['Nghị quyết 01/2014']); Điều dẫn [5, 7, 16, 18, 1 |
| 2.2 | ĐÚNG | 60.1 | verified | 27, 28, 301, 302 | đủ Điều [301, 302], văn bản ['LTM'] |
| 2.3 | MỘT PHẦN | 79.1 | verified | 4, 12, 13, 14, 30, 34, 44, 45, 47 | dẫn [44, 47]/[42, 44, 47], thiếu [42]; văn bản ['BLLĐ'] |
| 2.4 | MỘT PHẦN | 106.9 | verified | 17, 43, 66, 67, 111, 113, 114, 126, 136, 206 | dẫn [111, 136]/[111, 124, 125, 136], thiếu [124, 125]; văn bản ['BLTTDS'] |
| 2.5 | BỎ QUA | 53.9 | verified | 2, 3, 13, 14, 15, 111, 217, 319 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không có số Điều tiêu chí; dẫn văn bản ['BLDS', 'BLLĐ'], Điều [2, 3, 13, 14, 1 |
| 2.6 | ĐÚNG | 80.2 | partial | 12, 14, 20, 312, 314, 423, 424, 427 | đủ Điều [423, 424, 427], văn bản ['BLDS'] |
| 2.7 | MỘT PHẦN | 57.3 | partial | 68, 84 | dẫn [68, 84]/[68, 74, 84], thiếu [74]; văn bản ['BLDS', 'BLTTDS'] |
| 2.8 | SAI | 61.5 | verified | 5, 6, 8 | không dẫn Điều nào trong [156, 294, 420]; Điều bot dẫn [5, 6, 8]; văn bản [] |
| 2.9 | BỎ QUA | 57.1 | partial | 7 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí ([]); Điều dẫn [7]) |
| 2.10 | ĐÚNG | 60.3 | partial | 23, 68, 271, 310 | đủ Điều [310], văn bản ['BLTTDS'] |
| 3.1 | BỎ QUA | 93.6 | partial | 26, 72, 73, 74, 105 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí ([]); Điều dẫn [26, 72, 73, 74, 105]) |
| 3.2 | ĐÚNG | 75.7 | verified | 6, 10, 11, 27, 77, 105, 112 | đủ Điều [112], văn bản ['Luật SHTT'] |
| 3.3 | ĐÚNG | 91.5 | verified | 32, 93, 95, 96, 105, 136 | đủ Điều [95], văn bản ['Luật SHTT'] |
| 3.4 | ĐÚNG | 53.8 | verified | 4, 19, 20, 36, 39, 92 | đủ Điều [19, 20, 39], văn bản ['Luật SHTT'] |
| 3.5 | BỎ QUA | 78.1 | verified | 8, 22, 24, 96, 211, 213 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí ([]); Điều dẫn [8, 22, 24, 96, 211, 213]) |
| 3.6 | BỎ QUA | 93.0 | partial | 5, 11, 12, 18, 19, 20, 195, 284, 291 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không có số Điều tiêu chí; dẫn văn bản ['LTM'], Điều [5, 11, 12, 18, 19, 20, 1 |
| 3.7 | SAI | 75.5 | verified | 6, 16, 87, 181 | không dẫn Điều nào trong [142]; Điều bot dẫn [6, 16, 87, 181]; văn bản ['Luật SHTT'] |
| 3.8 | BỎ QUA | 50.7 | verified | 10, 11, 77 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không dẫn văn bản tiêu chí ([]); Điều dẫn [10, 11, 77]) |
| 3.9 | ĐÚNG | 94.6 | partial | 12, 16, 44, 52, 130 | đủ Điều [130], văn bản ['Luật SHTT'] |
| 3.10 | ĐÚNG | 74.8 | partial | 3, 5, 10, 44, 48, 60, 100 | đủ Điều [60], văn bản ['Luật SHTT'] |
| 4.1 | MỘT PHẦN | 73.1 | verified | 14, 15, 19, 27, 87, 211, 226 | dẫn [19]/[19, 38, 39, 41], thiếu [38, 39, 41]; văn bản ['LDN', 'NĐ 01/2021'] |
| 4.2 | SAI | 61.3 | verified | 8, 12, 47, 56 | không dẫn Điều nào trong [17]; Điều bot dẫn [8, 12, 47, 56]; văn bản ['LDN'] |
| 4.3 | BỎ QUA | 152.3 | verified | 7, 11, 14, 15, 20, 54 | tiêu chí không nêu số Điều — máy không chấm, LUẬT SƯ CHẤM nội dung (máy ghi nhận: không có số Điều tiêu chí; dẫn văn bản ['NHNN'], Điều [7, 11, 14, 15, 20, 54]  |
| 4.4 | MỘT PHẦN | 94.6 | verified | 57 | dẫn [57]/[57, 58], thiếu [58]; văn bản ['LDN'] |
| 4.5 | SAI | 71.4 | verified | 11, 23, 40, 60, 110 | không dẫn Điều nào trong [47]; Điều bot dẫn [11, 23, 40, 60, 110]; văn bản ['Luật Quản lý thuế'] |
| 4.6 | MỘT PHẦN | 115.4 | verified | 10, 44, 66, 96, 124, 125, 147 | dẫn [125]/[123, 125, 148], thiếu [123, 148]; văn bản ['LDN'] |
| 4.7 | MỘT PHẦN | 95.7 | verified | 1, 3, 7, 10, 11, 27, 28, 33, 37 | dẫn [37]/[22, 37, 38], thiếu [22, 38]; văn bản ['Luật Đầu tư'] |
| 4.8 | MỘT PHẦN | 132.0 | verified | 6, 16, 18, 23, 30, 31, 32, 34, 41 | dẫn [30, 31, 32]/[29, 30, 31, 32], thiếu [29]; văn bản ['Luật Đầu tư', 'Luật Đất đai'] |
| 4.9 | SAI | 90.1 | verified | 3, 4, 8, 9, 14, 28, 34, 36, 63 | không dẫn Điều nào trong [41, 44]; Điều bot dẫn [3, 4, 8, 9, 14, 28, 34, 36]; văn bản ['Luật Đầu tư'] |
| 4.10 | SAI | 81.5 | partial | 7, 10, 12, 17, 19, 21, 29, 189 | không dẫn Điều nào trong [26]; Điều bot dẫn [7, 10, 12, 17, 19, 21, 29, 189]; văn bản ['Luật Đầu tư'] |

Thời gian trả lời 40 KB: nhanh nhất 48.1s · trung vị 79.1s · chậm nhất 152.3s.

## 5. Thời gian các ca có gọi model

| Mã | Giây |
|---|---|
| CH-05 | 146.4 |
| CHUA-07 | 115.0 |
| CHUA-03 | 99.3 |
| CH-06 | 96.5 |
| CHUA-04 | 92.7 |
| CH-12 | 87.4 |
| CHUA-06 | 84.1 |
| CH-07 | 77.1 |
| PQ-12 | 69.2 |
| KT-01 | 57.3 |
| CH-08 | 55.7 |
| KT-05 | 50.4 |
| KT-06 | 49.8 |
| TH-01 | 47.4 |
| CH-01 | 45.1 |
| CH-18 | 43.1 |
| CH-17 | 40.6 |
| CH-03 | 40.3 |
| CH-10 | 39.7 |
| QT-07 | 37.6 |
| PNF-04 | 34.3 |
| CH-16 | 32.8 |
| KT-03 | 31.3 |
| CHUA-05 | 29.3 |
| CH-13 | 23.7 |
