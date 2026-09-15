import React, { useMemo, useState } from 'react';
import type { Source } from '../../types';
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  Paperclip,
  FileText,
  UserRound,
  Database,
  ExternalLink,
  Download,
  Eye,
} from 'lucide-react';

/**
 * Panel nguồn trích dẫn — gom theo TÀI LIỆU, kiểu NotebookLM / Perplexity.
 *
 * Bản cũ vẽ mỗi ĐOẠN thành một thẻ riêng: một file PDF đính kèm 55 đoạn thành
 * 55 thẻ "[File: x.pdf] — Liên quan 100%" xếp chồng, người đọc không biết bot
 * thực sự dựa vào đoạn nào (phản hồi 06/09/2026). Ở đây:
 *   - một thẻ cho mỗi tài liệu / file / đoạn người dùng dán;
 *   - trong thẻ, các đoạn ĐƯỢC DẪN (có chip số trong câu trả lời) đứng trước,
 *     đoạn còn lại thu gọn sau "Xem thêm";
 *   - thu gọn thì vẫn thấy một hàng chip tài liệu để biết bot đọc gì;
 *   - không có "Liên quan 100%" cho file đính kèm — điểm đó không phải độ liên
 *     quan, chỉ là "người dùng đưa cho bot".
 */

interface Props {
  sources: Source[];
  messageId: string | number;
  open: boolean;
  onToggle: () => void;
  /** Nguồn đang được soi (bấm chip trong câu trả lời) — sáng viền vài giây. */
  focusN: number | null;
  /** Số nguồn thật sự xuất hiện trong câu trả lời dưới dạng [Nguồn n]. */
  cited: Set<number>;
  onPreview: (docId: number) => void;
  onDownload: (docId: number, title: string) => void;
}

type Loai = 'document' | 'attachment' | 'user_provided' | 'system' | 'other';

export interface NhomNguon {
  key: string;
  loai: Loai;
  ten: string;
  khach: string | null;
  /** Nguồn mang metadata đại diện cho cả nhóm (số hiệu, hiệu lực, link). */
  dauMoc: Source;
  /** Các đoạn, đã xếp: được dẫn trước (theo số), rồi phần còn lại. */
  doan: Source[];
  soDan: number;
}

const RE_FILE = /^\[(?:Tóm tắt file|File): (.+)\]$/;
const RE_KH = /^\[KH: ([^\]]+)\]\s*/;

export function loaiNguon(s: Source): Loai {
  const k = s.kind;
  if (k === 'attachment' || k === 'user_provided' || k === 'system' || k === 'document') return k;
  if (RE_FILE.test(s.title || '')) return 'attachment';
  if ((s.title || '') === '[Người dùng cung cấp trong hội thoại]') return 'user_provided';
  return typeof s.document_id === 'number' || s.doc_id != null ? 'document' : 'other';
}

/** Tên hiện trên thẻ + tên khách (nếu tiêu đề mang tiền tố [KH: …]). */
export function tenNguon(s: Source, loai: Loai): { ten: string; khach: string | null } {
  let raw = s.title || s.document_title || 'Tài liệu nguồn';
  let khach: string | null = null;
  const kh = raw.match(RE_KH);
  if (kh) {
    khach = kh[1];
    raw = raw.slice(kh[0].length);
  }
  if (loai === 'attachment') {
    const m = raw.match(RE_FILE);
    return { ten: s.attachment_name || (m ? m[1] : raw), khach };
  }
  if (loai === 'user_provided') return { ten: 'Nội dung bạn dán vào hội thoại', khach };
  return { ten: raw, khach };
}

/** Gom các đoạn về từng tài liệu; nhóm có đoạn được dẫn đứng trước. */
export function nhomNguon(sources: Source[], cited: Set<number>): NhomNguon[] {
  const map = new Map<string, NhomNguon>();
  sources.forEach((s, idx) => {
    if (s.kind === 'notice') return;
    const loai = loaiNguon(s);
    const key =
      typeof s.document_id === 'number'
        ? `doc:${s.document_id}`
        : loai === 'attachment'
        ? `file:${s.attachment_name || s.title}`
        : loai === 'user_provided'
        ? 'user'
        : `t:${s.title || idx}`;
    let g = map.get(key);
    if (!g) {
      const { ten, khach } = tenNguon(s, loai);
      g = { key, loai, ten, khach, dauMoc: s, doan: [], soDan: 0 };
      map.set(key, g);
    }
    g.doan.push(s);
    if (typeof s.n === 'number' && cited.has(s.n)) g.soDan += 1;
    // Thẻ lấy metadata từ đoạn có nhiều thông tin nhất (số hiệu, link tải…)
    if (!g.dauMoc.so_hieu && s.so_hieu) g.dauMoc = s;
    if (typeof g.dauMoc.document_id !== 'number' && typeof s.document_id === 'number') g.dauMoc = s;
  });

  const nOf = (s: Source) => (typeof s.n === 'number' ? s.n : Number.MAX_SAFE_INTEGER);
  const daDan = (s: Source) => typeof s.n === 'number' && cited.has(s.n);
  const groups = [...map.values()];
  groups.forEach((g) => {
    g.doan.sort((a, b) => {
      const da = daDan(a) ? 0 : 1;
      const db = daDan(b) ? 0 : 1;
      return da - db || nOf(a) - nOf(b);
    });
  });
  const dauNhom = (g: NhomNguon) => (g.soDan > 0 ? nOf(g.doan[0]) : Number.MAX_SAFE_INTEGER);
  groups.sort((a, b) => dauNhom(a) - dauNhom(b));
  return groups;
}

/** Số đoạn KHÔNG được dẫn hiện sẵn trước khi phải bấm "Xem thêm". */
const DOAN_PHU_HIEN_SAN = 2;

const IconLoai: React.FC<{ loai: Loai; className?: string }> = ({ loai, className = 'w-4 h-4' }) => {
  if (loai === 'attachment') return <Paperclip className={className} />;
  if (loai === 'user_provided') return <UserRound className={className} />;
  if (loai === 'system') return <Database className={className} />;
  return <FileText className={className} />;
};

const NHAN_LOAI: Partial<Record<Loai, { text: string; cls: string }>> = {
  attachment: {
    text: 'Đính kèm',
    cls: 'bg-blue-50 dark:bg-blue-950/60 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800',
  },
  user_provided: {
    text: 'Bạn cung cấp',
    cls: 'bg-violet-50 dark:bg-violet-950/60 text-violet-800 dark:text-violet-200 border-violet-200 dark:border-violet-800',
  },
  system: {
    text: 'Dữ liệu hệ thống',
    cls: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-300 dark:border-slate-600',
  },
};

const chipSo = (dan: boolean) =>
  `inline-flex items-center justify-center shrink-0 text-[10px] font-bold rounded-full min-w-[18px] h-[18px] px-1 border mt-0.5 ${
    dan
      ? 'bg-hds-navy text-hds-gold border-hds-navy dark:bg-blue-600 dark:text-white dark:border-blue-500'
      : 'bg-white dark:bg-slate-900 text-slate-400 dark:text-slate-500 border-slate-300 dark:border-slate-600'
  }`;

const Doan: React.FC<{
  s: Source;
  loai: Loai;
  dan: boolean;
  focus: boolean;
  domId?: string;
}> = ({ s, loai, dan, focus, domId }) => {
  const [mo, setMo] = useState(false);
  const quote = s.quote ?? s.excerpt ?? s.snippet;
  const page = s.page_number ?? s.page;
  const section = s.section_title ?? s.section;
  const rawScore = s.relevance_score ?? s.score;
  // "khớp %" chỉ có nghĩa với kết quả tìm trong kho; file đính kèm luôn 1.0.
  const khop =
    loai === 'document' && typeof rawScore === 'number' && rawScore < 0.995
      ? Math.round(rawScore * 100)
      : null;
  const viTri = [
    page != null && page !== '' ? `Tr. ${page}` : null,
    section || null,
    s.source_locator || null,
    s.is_summary ? 'Tóm tắt cả file' : null,
  ].filter(Boolean) as string[];

  return (
    <li
      id={domId}
      className={`flex items-start gap-2.5 py-2 transition-shadow rounded-md ${
        focus ? 'ring-2 ring-hds-gold/60 bg-amber-50/60 dark:bg-amber-950/30 px-1.5 -mx-1.5' : ''
      }`}
    >
      <span className={chipSo(dan)} title={dan ? `Được dẫn trong câu trả lời [Nguồn ${s.n}]` : `Nguồn ${s.n} — bot đã đọc nhưng không dẫn`}>
        {typeof s.n === 'number' ? s.n : '·'}
      </span>
      <div className="min-w-0 flex-1">
        {(viTri.length > 0 || khop !== null) && (
          <div className="flex flex-wrap items-center gap-x-1.5 text-[10px] text-slate-500 dark:text-slate-400 leading-4">
            {viTri.map((v, i) => (
              <span key={i}>
                {i > 0 && <span className="mx-0.5 opacity-60">·</span>}
                {v}
              </span>
            ))}
            {khop !== null && (
              <span className="ml-auto tabular-nums" title="Mức khớp giữa câu hỏi và đoạn này khi tìm trong kho">
                khớp {khop}%
              </span>
            )}
          </div>
        )}
        {quote && (
          <p
            onClick={() => setMo((v) => !v)}
            title={mo ? 'Bấm để thu gọn' : 'Bấm để xem trọn đoạn'}
            className={`mt-0.5 text-[11.5px] leading-relaxed text-slate-700 dark:text-slate-300 break-words cursor-pointer ${
              mo ? '' : 'line-clamp-3'
            }`}
          >
            {quote}
          </p>
        )}
      </div>
    </li>
  );
};

const The: React.FC<{
  g: NhomNguon;
  messageId: string | number;
  cited: Set<number>;
  focusN: number | null;
  onPreview: (docId: number) => void;
  onDownload: (docId: number, title: string) => void;
}> = ({ g, messageId, cited, focusN, onPreview, onDownload }) => {
  const [xemHet, setXemHet] = useState(false);
  const daDan = (s: Source) => typeof s.n === 'number' && cited.has(s.n);
  const soHienSan = g.soDan + DOAN_PHU_HIEN_SAN;
  // Đoạn đang được soi nằm trong phần thu gọn thì tự bung ra.
  const focusTrongPhanAn = focusN != null && g.doan.slice(soHienSan).some((s) => s.n === focusN);
  const hienHet = xemHet || focusTrongPhanAn;
  const doanHien = hienHet ? g.doan : g.doan.slice(0, soHienSan);
  const conAn = g.doan.length - doanHien.length;
  const m = g.dauMoc;
  const nhan = NHAN_LOAI[g.loai];
  const docId = typeof m.document_id === 'number' ? m.document_id : null;
  const driveId = m.drive_file_id && !String(m.drive_file_id).startsWith('local:') ? String(m.drive_file_id) : null;
  const iconBtn =
    'p-1.5 rounded-lg text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 hover:bg-white dark:hover:bg-slate-700 transition-colors';

  return (
    <li
      id={`msg-${messageId}-grp-${g.key}`}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/60 overflow-hidden"
    >
      <div className="flex items-start gap-2.5 px-3 py-2 bg-slate-50 dark:bg-slate-800/60">
        <span className="mt-0.5 text-hds-navy dark:text-blue-300 shrink-0">
          <IconLoai loai={g.loai} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-xs text-slate-900 dark:text-slate-100 break-words" title={g.ten}>
              {g.ten}
            </span>
            {nhan && (
              <span className={`text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border ${nhan.cls}`}>
                {nhan.text}
              </span>
            )}
            {g.khach && (
              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded border bg-amber-50 dark:bg-amber-950/50 text-amber-900 dark:text-amber-200 border-amber-200 dark:border-amber-800">
                KH: {g.khach}
              </span>
            )}
            {/* Hiệu lực văn bản luật: nội dung trích vẫn đúng nguyên văn nên chỉ
                badge này báo được nguồn là luật đã chết — phải đứng cạnh tên. */}
            {m.trang_thai_hieu_luc === 'het_hieu_luc' && (
              <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-red-100 text-red-700">
                Hết hiệu lực
              </span>
            )}
            {m.trang_thai_hieu_luc === 'het_hieu_luc_mot_phan' && (
              <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                Đã sửa đổi
              </span>
            )}
            <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400 tabular-nums shrink-0">
              {g.soDan > 0 ? `${g.soDan}/${g.doan.length} đoạn dẫn` : `${g.doan.length} đoạn`}
            </span>
          </div>
          {(m.so_hieu || m.ngay_ban_hanh || m.ngay_hieu_luc || m.source_version != null) && (
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-slate-500 dark:text-slate-400">
              {m.so_hieu && (
                <span className="font-semibold text-slate-600 dark:text-slate-300">
                  {[m.loai_van_ban, m.trich_yeu].filter(Boolean).join(' ')}
                  {m.loai_van_ban || m.trich_yeu ? ' — ' : ''}
                  Số {m.so_hieu}
                </span>
              )}
              {m.ngay_ban_hanh && <span>BH {m.ngay_ban_hanh}</span>}
              {m.ngay_hieu_luc && <span>HL {m.ngay_hieu_luc}</span>}
              {m.source_version != null && <span>Phiên bản {m.source_version}</span>}
            </div>
          )}
          {m.thay_the_boi && (
            <div className="mt-0.5 text-[10px] font-semibold text-red-600 dark:text-red-400">
              → Đã bị thay thế/sửa đổi bởi: {m.thay_the_boi}
            </div>
          )}
        </div>
        {(driveId || docId !== null) && (
          <div className="flex items-center gap-0.5 shrink-0 -mr-1">
            {driveId && (
              <a
                href={`https://drive.google.com/file/d/${driveId}/view`}
                target="_blank"
                rel="noopener noreferrer"
                className={iconBtn}
                title="Mở bản gốc trên Drive"
                aria-label="Mở bản gốc trên Drive"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
            {docId !== null && (
              <button
                type="button"
                onClick={() => onPreview(docId)}
                className={iconBtn}
                title="Xem trước trong trình duyệt (PDF/ảnh xem thẳng, file Word xem bản PDF)"
                aria-label="Xem trước"
              >
                <Eye className="w-3.5 h-3.5" />
              </button>
            )}
            {docId !== null && (
              <button
                type="button"
                onClick={() => onDownload(docId, m.title)}
                className={iconBtn}
                title="Tải về bản gốc"
                aria-label="Tải về"
              >
                <Download className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      <ul className="px-3 divide-y divide-slate-100 dark:divide-slate-800">
        {doanHien.map((s, i) => (
          <Doan
            key={`${s.n ?? 'x'}-${s.chunk_id ?? i}`}
            s={s}
            loai={g.loai}
            dan={daDan(s)}
            focus={focusN != null && s.n === focusN}
            domId={typeof s.n === 'number' ? `msg-${messageId}-src-${s.n}` : undefined}
          />
        ))}
      </ul>
      {conAn > 0 && (
        <button
          type="button"
          onClick={() => setXemHet(true)}
          className="w-full text-left px-3 py-1.5 text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:bg-slate-50 dark:hover:bg-slate-800/60 border-t border-slate-100 dark:border-slate-800"
        >
          Xem thêm {conAn} đoạn bot đã đọc nhưng không dẫn
        </button>
      )}
      {hienHet && xemHet && g.doan.length > soHienSan && (
        <button
          type="button"
          onClick={() => setXemHet(false)}
          className="w-full text-left px-3 py-1.5 text-[11px] font-semibold text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/60 border-t border-slate-100 dark:border-slate-800"
        >
          Thu gọn
        </button>
      )}
    </li>
  );
};

/** Hàng chip tài liệu khi panel đang thu gọn — thấy ngay bot đọc gì. */
const HANG_CHIP_TOI_DA = 6;

export const SourcePanel: React.FC<Props> = ({
  sources,
  messageId,
  open,
  onToggle,
  focusN,
  cited,
  onPreview,
  onDownload,
}) => {
  const nhom = useMemo(() => nhomNguon(sources, cited), [sources, cited]);
  if (nhom.length === 0) return null;
  const tongDoan = nhom.reduce((a, g) => a + g.doan.length, 0);
  const tongDan = nhom.reduce((a, g) => a + g.soDan, 0);

  const moToiNhom = (key: string) => {
    if (!open) onToggle();
    requestAnimationFrame(() => {
      document
        .getElementById(`msg-${messageId}-grp-${key}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  };

  return (
    <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-between w-full text-xs font-semibold px-1 py-1 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5 text-hds-navy dark:text-blue-300">
          <BookOpen className="w-4 h-4 text-hds-gold" />
          <span>Nguồn trích dẫn</span>
          <span className="font-normal text-slate-500 dark:text-slate-400 tabular-nums">
            · {nhom.length} tài liệu
            {tongDan > 0 ? ` · ${tongDan} đoạn dẫn` : ` · ${tongDoan} đoạn`}
          </span>
        </span>
        {open ? (
          <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
        )}
      </button>

      {!open && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {nhom.slice(0, HANG_CHIP_TOI_DA).map((g) => (
            <button
              key={g.key}
              type="button"
              onClick={() => moToiNhom(g.key)}
              className="inline-flex items-center gap-1.5 max-w-[260px] rounded-full border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 hover:bg-white dark:hover:bg-slate-800 hover:border-hds-navy/40 px-2.5 py-1 text-[11px] text-slate-700 dark:text-slate-200 transition-colors"
              title={g.ten}
            >
              <span className="text-hds-navy dark:text-blue-300 shrink-0">
                <IconLoai loai={g.loai} className="w-3.5 h-3.5" />
              </span>
              <span className="truncate">{g.ten}</span>
              {g.soDan > 0 && (
                <span className="shrink-0 rounded-full bg-hds-navy text-hds-gold dark:bg-blue-600 dark:text-white text-[9px] font-bold px-1.5 leading-4">
                  {g.soDan}
                </span>
              )}
            </button>
          ))}
          {nhom.length > HANG_CHIP_TOI_DA && (
            <button
              type="button"
              onClick={onToggle}
              className="inline-flex items-center rounded-full px-2 py-1 text-[11px] text-slate-500 dark:text-slate-400 hover:underline"
            >
              +{nhom.length - HANG_CHIP_TOI_DA} nữa
            </button>
          )}
        </div>
      )}

      {open && (
        <ul className="mt-2 space-y-2">
          {nhom.map((g) => (
            <The
              key={g.key}
              g={g}
              messageId={messageId}
              cited={cited}
              focusN={focusN}
              onPreview={onPreview}
              onDownload={onDownload}
            />
          ))}
        </ul>
      )}
    </div>
  );
};
