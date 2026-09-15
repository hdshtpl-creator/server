import React, { useState } from 'react';
import type { SoSanhDoan, SoSanhKetQua } from '../../types';

/**
 * DiffView — hai cột "bản cũ | bản mới", tô phần xoá (đỏ, gạch ngang) và
 * phần thêm (xanh) ở mức TỪ. Dùng chung cho so sánh phiên bản bản thảo
 * (tab Soạn tài liệu) và lịch sử sửa nội dung tài liệu kho.
 *
 * Đoạn không đổi được ẩn bớt khi văn bản dài: luật sư cần thấy CHỖ KHÁC,
 * không cần đọc lại 30 trang giống nhau — nhưng vẫn giữ 1 đoạn trước/sau
 * mỗi chỗ khác để có ngữ cảnh.
 */
const inlineOld = (d: SoSanhDoan) => (
  <>
    {d.phan.filter((p) => p.op !== 'insert').map((p, i) =>
      p.op === 'delete' ? (
        <span key={i} className="bg-red-100 dark:bg-red-950/60 text-red-800 dark:text-red-300 line-through decoration-red-500">{p.text}</span>
      ) : (
        <span key={i}>{p.text}</span>
      ),
    )}
  </>
);
const inlineNew = (d: SoSanhDoan) => (
  <>
    {d.phan.filter((p) => p.op !== 'delete').map((p, i) =>
      p.op === 'insert' ? (
        <span key={i} className="bg-emerald-100 dark:bg-emerald-950/60 text-emerald-900 dark:text-emerald-300 underline decoration-emerald-500">{p.text}</span>
      ) : (
        <span key={i}>{p.text}</span>
      ),
    )}
  </>
);

export const DiffStats: React.FC<{ ketQua: SoSanhKetQua }> = ({ ketQua }) => {
  const t = ketQua.thong_ke;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className="px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 font-bold">+{t.them} từ</span>
      <span className="px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-950/50 text-red-800 dark:text-red-300 font-bold">−{t.xoa} từ</span>
      <span className="text-slate-500 dark:text-slate-400">
        {t.doan_sua} đoạn sửa · {t.doan_them} đoạn thêm · {t.doan_xoa} đoạn xoá · giống nhau {Math.round((t.giong_nhau || 0) * 100)}%
      </span>
    </div>
  );
};

export const DiffView: React.FC<{ ketQua: SoSanhKetQua; labelCu?: string; labelMoi?: string }> = ({
  ketQua, labelCu = 'Bản cũ', labelMoi = 'Bản mới',
}) => {
  const [showAll, setShowAll] = useState(false);
  const doan = ketQua.doan || [];
  // Chỉ mục các đoạn cần hiện: mọi đoạn khác + 1 đoạn kề mỗi bên.
  const keep = new Set<number>();
  doan.forEach((d, i) => {
    if (d.op !== 'equal') { keep.add(i - 1); keep.add(i); keep.add(i + 1); }
  });
  const hidden = doan.filter((d, i) => d.op === 'equal' && !keep.has(i)).length;
  const rows: Array<{ idx: number; d: SoSanhDoan } | { gap: number }> = [];
  let gap = 0;
  doan.forEach((d, i) => {
    if (showAll || d.op !== 'equal' || keep.has(i)) {
      if (gap) { rows.push({ gap }); gap = 0; }
      rows.push({ idx: i, d });
    } else gap += 1;
  });
  if (gap) rows.push({ gap });

  if (!doan.length) {
    return <p className="text-xs text-slate-500 italic">Hai bản trống.</p>;
  }
  const allEqual = doan.every((d) => d.op === 'equal');
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <DiffStats ketQua={ketQua} />
        {hidden > 0 && (
          <button type="button" onClick={() => setShowAll((v) => !v)} className="text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:underline">
            {showAll ? 'Ẩn đoạn không đổi' : `Hiện ${hidden} đoạn không đổi`}
          </button>
        )}
      </div>
      {allEqual && <p className="text-xs text-emerald-700 dark:text-emerald-300 font-semibold">Hai phiên bản giống hệt nhau.</p>}
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden text-xs">
        <div className="grid grid-cols-2 bg-slate-100 dark:bg-slate-800 font-bold text-[11px]">
          <div className="px-3 py-1.5 border-r border-slate-200 dark:border-slate-700">{labelCu}</div>
          <div className="px-3 py-1.5">{labelMoi}</div>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {rows.map((r, i) =>
            'gap' in r ? (
              <div key={`g${i}`} className="grid grid-cols-2 text-[10px] text-slate-400 bg-slate-50 dark:bg-slate-900/60">
                <div className="px-3 py-1 border-r border-slate-100 dark:border-slate-800">… {r.gap} đoạn không đổi …</div>
                <div className="px-3 py-1">… {r.gap} đoạn không đổi …</div>
              </div>
            ) : (
              <div
                key={r.idx}
                className={`grid grid-cols-2 border-t border-slate-100 dark:border-slate-800 ${
                  r.d.op === 'equal' ? 'text-slate-500 dark:text-slate-400' : 'text-slate-800 dark:text-slate-100'
                }`}
              >
                <div className={`px-3 py-1.5 border-r border-slate-100 dark:border-slate-800 whitespace-pre-wrap break-words ${r.d.op === 'delete' ? 'bg-red-50/70 dark:bg-red-950/30' : ''}`}>
                  {r.d.cu == null ? <span className="text-slate-300 dark:text-slate-600">—</span> : inlineOld(r.d)}
                </div>
                <div className={`px-3 py-1.5 whitespace-pre-wrap break-words ${r.d.op === 'insert' ? 'bg-emerald-50/70 dark:bg-emerald-950/30' : ''}`}>
                  {r.d.moi == null ? <span className="text-slate-300 dark:text-slate-600">—</span> : inlineNew(r.d)}
                </div>
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
};
