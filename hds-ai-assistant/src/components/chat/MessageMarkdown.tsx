import React, { useMemo } from 'react';

/**
 * Renderer markdown TỐI GIẢN cho tin nhắn của bot, kiểu NotebookLM.
 *
 * Vì sao không dùng react-markdown: model chỉ sinh một tập markdown rất hẹp
 * (đậm, nghiêng, gạch đầu dòng, tiêu đề, trích dẫn), trong khi thư viện đầy đủ
 * kéo theo cả cây phụ thuộc và một bề mặt XSS phải canh chừng. Tự viết ~100
 * dòng thì kiểm soát được từng thứ hiển thị — và quan trọng nhất là biến
 * [Nguồn n] thành CHIP SỐ BẤM ĐƯỢC, thứ react-markdown không làm sẵn.
 *
 * An toàn: KHÔNG có dangerouslySetInnerHTML. Mọi thứ đi qua React element nên
 * chữ trong tài liệu không bao giờ thành HTML sống.
 */

interface Props {
  text: string;
  /** Bấm chip [Nguồn n] → mở panel nguồn và cuộn tới đúng nguồn đó. */
  onCitationClick?: (n: number) => void;
  /** Các số nguồn hợp lệ; chip ngoài danh sách này hiện xám, không bấm được. */
  validSources?: Set<number>;
}

const CITE_RE = /\[\s*Nguồn\s+(\d+)\s*\]/gi;
// **đậm** trước, *nghiêng* sau — thứ tự regex quyết định đúng sai.
const BOLD_RE = /\*\*(.+?)\*\*/g;
const ITALIC_RE = /(?<!\*)\*(?!\*)([^*\n]+)\*(?!\*)/g;

/** Chip số kiểu NotebookLM: hình tròn nhỏ, bấm để soi nguồn. */
const CitationChip: React.FC<{
  n: number;
  valid: boolean;
  onClick?: (n: number) => void;
}> = ({ n, valid, onClick }) => (
  <button
    type="button"
    disabled={!valid}
    onClick={() => valid && onClick?.(n)}
    title={valid ? `Mở Nguồn ${n}` : `Nguồn ${n} không có trong danh sách`}
    className={`inline-flex items-center justify-center align-super text-[9px] font-bold rounded-full min-w-[16px] h-4 px-0.5 mx-0.5 border transition-colors ${
      valid
        ? 'bg-hds-soft dark:bg-blue-950 text-hds-navy dark:text-blue-300 border-blue-200 dark:border-blue-800 hover:bg-hds-navy hover:text-white dark:hover:bg-blue-600 cursor-pointer'
        : 'bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700 cursor-default'
    }`}
  >
    {n}
  </button>
);

/** Đổi chuỗi thường → mảng node có đậm/nghiêng/chip nguồn. */
function renderInline(
  text: string,
  keyBase: string,
  onCitationClick?: (n: number) => void,
  validSources?: Set<number>,
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  // Tách theo chip nguồn trước — chip là element, không phải chữ.
  const parts = text.split(CITE_RE);
  // split với capture group trả [chữ, số, chữ, số, …]: phần lẻ là số nguồn.
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const n = parseInt(part, 10);
      out.push(
        <CitationChip
          key={`${keyBase}-c${i}`}
          n={n}
          valid={validSources ? validSources.has(n) : true}
          onClick={onCitationClick}
        />,
      );
      return;
    }
    // Trong phần chữ: đậm rồi nghiêng. Đi qua React nên không có HTML sống.
    const boldParts = part.split(BOLD_RE);
    boldParts.forEach((seg, j) => {
      const key = `${keyBase}-${i}-${j}`;
      if (j % 2 === 1) {
        out.push(<strong key={key}>{seg}</strong>);
        return;
      }
      const italicParts = seg.split(ITALIC_RE);
      italicParts.forEach((it, k) => {
        if (k % 2 === 1) out.push(<em key={`${key}-i${k}`}>{it}</em>);
        else if (it) out.push(<React.Fragment key={`${key}-t${k}`}>{it}</React.Fragment>);
      });
    });
  });
  return out;
}

export const MessageMarkdown: React.FC<Props> = ({ text, onCitationClick, validSources }) => {
  const blocks = useMemo(() => (text || '').split(/\n/), [text]);

  const rendered: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let listOrdered = false;

  const flushList = (key: string) => {
    if (!listItems.length) return;
    const cls = 'my-1.5 ml-1 space-y-1';
    rendered.push(
      listOrdered
        ? <ol key={key} className={`${cls} list-decimal list-inside`}>{listItems}</ol>
        : <ul key={key} className={cls}>{listItems}</ul>,
    );
    listItems = [];
  };

  blocks.forEach((line, idx) => {
    const key = `l${idx}`;
    const trimmed = line.trim();

    // Gạch đầu dòng: -, ·, • và danh sách số "1." — gom vào một <ul>/<ol>.
    const bullet = trimmed.match(/^[-·•]\s+(.*)$/);
    const numbered = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const body = (bullet ? bullet[1] : numbered![2]) as string;
      const wasOrdered = listOrdered;
      listOrdered = Boolean(numbered);
      if (listItems.length && wasOrdered !== listOrdered) flushList(`${key}-sw`);
      listItems.push(
        <li key={key} className={listOrdered ? '' : 'flex gap-2'}>
          {!listOrdered && <span className="text-hds-gold shrink-0 select-none">•</span>}
          <span className="min-w-0">{renderInline(body, key, onCitationClick, validSources)}</span>
        </li>,
      );
      return;
    }
    flushList(`${key}-f`);

    if (!trimmed) return; // dòng trống — khoảng cách đã có margin của block lo

    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const sizes = ['text-base', 'text-[15px]', 'text-sm', 'text-sm'];
      rendered.push(
        <div key={key} className={`${sizes[level - 1]} font-bold text-slate-900 dark:text-slate-100 mt-3 mb-1`}>
          {renderInline(heading[2], key, onCitationClick, validSources)}
        </div>,
      );
      return;
    }

    if (trimmed === '---' || trimmed === '***') {
      rendered.push(<hr key={key} className="my-2.5 border-slate-200 dark:border-slate-700" />);
      return;
    }

    if (trimmed.startsWith('>')) {
      rendered.push(
        <blockquote key={key} className="border-l-2 border-hds-gold pl-3 my-1.5 text-slate-600 dark:text-slate-400 italic">
          {renderInline(trimmed.replace(/^>\s?/, ''), key, onCitationClick, validSources)}
        </blockquote>,
      );
      return;
    }

    rendered.push(
      <p key={key} className="my-1">
        {renderInline(line, key, onCitationClick, validSources)}
      </p>,
    );
  });
  flushList('tail');

  return <div className="text-sm leading-relaxed break-words">{rendered}</div>;
};
