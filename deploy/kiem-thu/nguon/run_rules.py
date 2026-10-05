import sys, json, os
from pathlib import Path
sys.path.insert(0, '.')
os.environ.setdefault('DATABASE_URL','postgresql://x:y@127.0.0.1:1/none')
from app import ingest, ra_soat_rui_ro as rr, kiem_tra_mau_thuan as km, autofill
D = Path('../deploy/kiem-thu/du-lieu-mau')
out = {}
for f in sorted(D.glob('RR0*.docx')) + [D/'AT01_HD_co_chen_lenh.docx']:
    t = ingest.extract_text(f)
    r = rr.ra_soat(t, tieu_de=f.stem)
    print('=====', f.name, '| loai:', r['loai'], r['ten_loai'], 'tin', r['do_tin_cay'], '| tong_ket', r['tong_ket'], '| so_dieu', r['so_dieu_khoan'])
    for m in r['muc']:
        print('  ', m['trang_thai'].upper(), '|', m['ten'], '|', (m.get('gia_tri') or m.get('vi_tri') or ''), '|', m.get('can_cu',''))
    muc = km.trich_xuat_quy_tac(t)
    pq = km.kiem_tra_quy_tac(muc)
    print('  -- KTMT trich', len(muc), 'muc; phan quyet:')
    for p in pq:
        print('     ', {k: p.get(k) for k in ('ket_luan','noi_dung','loai','gia_tri','vi_tri','ly_do','can_cu') if p.get(k) is not None})
for f in ['TD01_CCCD_gia.docx','TD02_CV_gia.docx']:
    t = ingest.extract_text(D/f)
    print('=====', f, json.dumps(autofill.extract_person_fields(t), ensure_ascii=False))
t = (D/'KTMT01_yeu_cau_sua_ban_nhap.txt').read_text(encoding='utf-8')
print('===== KTMT01 text rules')
for p in km.kiem_tra_quy_tac(km.trich_xuat_quy_tac(t)):
    print('     ', {k: p.get(k) for k in ('ket_luan','noi_dung','loai','gia_tri','ly_do','can_cu') if p.get(k) is not None})
