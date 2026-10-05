# Nguồn sinh bộ kiểm thử

`KICH_BAN_KIEM_THU.md` và `KICH_BAN_KIEM_THU.xlsx` được **sinh từ các tệp trong thư mục này** —
sửa ca kiểm thử thì sửa ở đây rồi sinh lại, đừng sửa tay hai tệp kết quả (sẽ lệch nhau).

| Tệp | Nội dung |
|---|---|
| `cases_a.py`, `cases_b.py` | Toàn bộ ca kiểm thử (mã, tài khoản, đầu vào, kết quả mong đợi) |
| `kb_cases.py` + `kb40.json` | 40 kịch bản pháp lý của HDS (từ *Kịch bản test AI.docx*) + điều luật bắt buộc |
| `findings.py` | Phát hiện khi rà soát, tài liệu lệch, ma trận hợp đồng, danh mục chức năng |
| `md_static.py` | Phần văn xuôi cố định (mở đầu, chuẩn bị, cách ghi kết quả, tiêu chí) |
| `build_docs.py` | Sinh md + xlsx + `du-lieu-mau/README.md` |
| `make_inputs.py` | Sinh các file .docx/.txt trong `du-lieu-mau/` |
| `run_rules.py` | Chạy file mẫu qua bộ quy tắc thật (`ra_soat_rui_ro`, `kiem_tra_mau_thuan`, `autofill`) để lấy kết quả mong đợi |

```bash
# từ gốc repo, dùng venv có python-docx + openpyxl (máy dev: D:\hds-venv)
python deploy/kiem-thu/nguon/make_inputs.py deploy/kiem-thu/du-lieu-mau
python deploy/kiem-thu/nguon/build_docs.py  deploy/kiem-thu
# đổi quy tắc rà soát / kiểm tra mâu thuẫn → chạy lại để cập nhật kết quả mong đợi trong cases_*.py
cd hds-ai && python ../deploy/kiem-thu/nguon/run_rules.py
```

Bộ bài cho **nhân viên** (truy vấn, tạo tài liệu, kiểm tra pháp lý): `nhan_vien.py` → `build_nhan_vien.py`
sinh `KIEM_THU_CHO_NHAN_VIEN.md` + `PHIEU_KIEM_THU_NHAN_VIEN.xlsx`:

```bash
python deploy/kiem-thu/nguon/build_nhan_vien.py deploy/kiem-thu
```

**Bộ câu hỏi mẫu cho nhân viên thử thêm** (05/10/2026) — mở rộng từng loại bài + bộ câu cho lô
2.304 hợp đồng tiếng Anh Hoa Kỳ (SEC): câu hỏi ở `cau_hoi_mau.py`, máy đo phần tìm nguồn ở
`do_nguon.py` (chạy TRÊN MÁY CHỦ, chỉ gọi `rag.prepare`, không gọi model) → `do_nguon_0510.json` (lần đo
đầu, TRƯỚC sửa) và `do_nguon_0510_sau.json` (SAU khi sửa P1–P8 và cập nhật máy chủ cùng ngày);
`build_cau_hoi_mau.py` sinh `BO_CAU_HOI_MAU.md`, `BO_CAU_HOI_TAI_LIEU_TIENG_ANH.md`, `PHIEU_CAU_HOI_MAU.xlsx`:

```bash
# trên máy chủ: scp cau_hoi_mau.py do_nguon.py lên /tmp rồi
cd ~/hds-ai-full/hds-ai && set -a && . ./.env && set +a && PYTHONPATH=/tmp .venv/bin/python /tmp/do_nguon.py > /tmp/do_nguon.json
# trên máy dev: chép /tmp/do_nguon.json về nguon/do_nguon_0510_sau.json (lần đo mới nhất) rồi
python deploy/kiem-thu/nguon/build_cau_hoi_mau.py deploy/kiem-thu
```
