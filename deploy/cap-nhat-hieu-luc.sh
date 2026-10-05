#!/usr/bin/env bash
# Do trang thai hieu luc tu vbpl.vn (tep ~/vbpl_hieu_luc.tsv) vao cot
# trang_thai_hieu_luc — cron moi gio (crontab: 7 * * * * … ~/cap-nhat-hieu-luc.sh).
#
# Chu du an chot 17/09/2026: lay vbpl.vn lam chuan. NHUNG (05/10/2026): tep tsv
# cua dot tai ve KHONG CO gia tri "het_hieu_luc" nao (55.485 con_hieu_luc, 4.985
# het_hieu_luc_mot_phan, 2.088 chua_ro) — luc tai da doc sai cot trang thai, nen
# van ban da chet (Luat Dat dai 2013…) bi ghi "con hieu luc" lai moi gio.
# Tu 05/10/2026: tep tsv KHONG duoc de len 'het_hieu_luc' — nhan nay chi do bo
# boc quan he dat (cau "… het hieu luc ke tu …" / "thay the" trong chinh van ban
# thay the dang nam trong kho, xem app/backfill_hieu_luc.py).
#
# Ban goc nam o ~/cap-nhat-hieu-luc.sh tren may chu; ban nay la nguon trong repo.
# Chay lai duoc nhieu lan: chi dong vao dong nao dang khac gia tri chuan.
set -u
TSV=/home/pc/vbpl_hieu_luc.tsv
[ -s "$TSV" ] || { echo "thieu $TSV"; exit 1; }
{
  echo "CREATE TEMP TABLE t(khoa text, tt text);"
  echo "COPY t FROM STDIN;"
  cat "$TSV"
  echo "\."
  cat <<"S'L"
CREATE INDEX ON t(khoa);
UPDATE documents d
   SET trang_thai_hieu_luc = t.tt, updated_at = now()
  FROM t
 WHERE regexp_replace(regexp_replace(d.source_path, '^.*/', ''), '\.[^.]*$', '') = t.khoa
   AND d.source_path LIKE '%/1. VĂN BẢN PHÁP LUẬT/%'
   AND coalesce(d.active, true)
   AND coalesce(d.trang_thai_hieu_luc, 'chua_ro') <> 'het_hieu_luc'
   AND coalesce(d.trang_thai_hieu_luc, 'chua_ro') IS DISTINCT FROM t.tt;
S'L
echo "\echo $(date '+%F %T')"
} | docker exec -i hds-postgres psql -U hds -d hdsai -v ON_ERROR_STOP=1
