import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { ChatSearchHit } from '../../types';
import { Search, StickyNote, Trash2, Plus, X, Sparkles, Loader2, CornerDownLeft } from 'lucide-react';

/**
 * Khung bên trái của trợ lý — KHÔNG còn danh sách nhiều cuộc trò chuyện.
 * Mỗi người một khung chat bền, nên chỗ này thành:
 *   · ô Tìm kiếm trong lịch sử chat của chính mình,
 *   · khung Ghi chú cá nhân (điều quan trọng cần nhớ).
 */
export const ConversationSidebar: React.FC = () => {
  const { isSidebarOpen, setSidebarOpen, notes, reloadNotes, saveNote, removeNote, showToast } =
    useApp();

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ChatSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const [noteText, setNoteText] = useState('');
  const [savingNote, setSavingNote] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    reloadNotes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tìm kiếm có giãn cách (debounce) để không gọi backend mỗi phím
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setSearched(false);
      return;
    }
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        setResults(await api.searchChat(q));
      } catch (err: any) {
        showToast(err?.message || 'Không tìm được.', 'error');
      } finally {
        setSearching(false);
        setSearched(true);
      }
    }, 350);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const jumpToMessage = (id: number) => {
    const el = document.getElementById(`chatmsg-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-hds-gold');
      setTimeout(() => el.classList.remove('ring-2', 'ring-hds-gold'), 1600);
      setSidebarOpen(false);
    } else {
      showToast('Đoạn này nằm ngoài phần đang hiển thị.', 'info');
    }
  };

  const handleAddNote = async () => {
    const content = noteText.trim();
    if (!content) return;
    setSavingNote(true);
    try {
      await saveNote(content);
      setNoteText('');
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được ghi chú.', 'error');
    } finally {
      setSavingNote(false);
    }
  };

  return (
    <>
      {isSidebarOpen && (
        <div
          className="lg:hidden fixed inset-0 top-16 bg-slate-900/50 z-20 animate-fade-in"
          onClick={() => setSidebarOpen(false)}
          role="presentation"
        />
      )}

      <aside
        className={`w-72 bg-hds-navy-dark text-slate-200 border-r border-white/10 flex flex-col shrink-0
          fixed lg:static top-16 bottom-0 left-0 z-30 lg:z-auto lg:inset-auto lg:h-full
          transition-transform duration-200 ease-out
          ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
        aria-label="Bảng trợ lý"
      >
        {/* Tìm kiếm trong lịch sử chat */}
        <div className="p-3 border-b border-white/10 space-y-2">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Tìm trong đoạn chat cũ…"
              aria-label="Tìm trong lịch sử trò chuyện"
              className="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-xl text-xs text-slate-100 placeholder-slate-400 focus:ring-2 focus:ring-hds-gold/60 focus:outline-none"
            />
          </div>

          {searching && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 px-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Đang tìm…
            </div>
          )}

          {searched && !searching && (
            <div className="space-y-1 max-h-52 overflow-y-auto">
              {results.length === 0 ? (
                <p className="text-[11px] text-slate-500 px-1 py-1">Không thấy đoạn nào khớp.</p>
              ) : (
                results.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => jumpToMessage(r.id)}
                    className="w-full text-left bg-white/5 hover:bg-white/10 rounded-lg p-2 transition-colors"
                  >
                    <span className="text-[9px] font-bold uppercase tracking-wider text-hds-gold/80">
                      {r.role === 'user' ? 'Bạn hỏi' : 'Trợ lý'}
                    </span>
                    <span className="block text-[11px] text-slate-300 leading-snug line-clamp-2 mt-0.5">
                      {r.content}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Ghi chú cá nhân */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="px-3 pt-3 pb-1 flex items-center gap-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            <StickyNote className="w-3.5 h-3.5 text-hds-gold" />
            Ghi chú của tôi
          </div>

          {/* Thêm ghi chú nhanh */}
          <div className="px-3 pb-2">
            <div className="flex items-start gap-1.5">
              <textarea
                rows={2}
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    handleAddNote();
                  }
                }}
                placeholder="Ghi nhanh điều cần nhớ… (Ctrl+Enter để lưu)"
                className="flex-1 px-2.5 py-1.5 bg-white/5 border border-white/10 rounded-lg text-[11px] text-slate-100 placeholder-slate-400 focus:ring-2 focus:ring-hds-gold/60 focus:outline-none resize-none"
              />
              <button
                onClick={handleAddNote}
                disabled={!noteText.trim() || savingNote}
                title="Lưu ghi chú"
                className="p-2 bg-hds-navy hover:bg-hds-navy-light rounded-lg border border-white/15 shrink-0 disabled:opacity-40 transition-colors"
              >
                {savingNote ? (
                  <Loader2 className="w-4 h-4 animate-spin text-hds-gold" />
                ) : (
                  <Plus className="w-4 h-4 text-hds-gold" />
                )}
              </button>
            </div>
          </div>

          {/* Danh sách ghi chú */}
          <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5 min-h-0">
            {notes.length === 0 ? (
              <p className="text-[11px] text-slate-500 px-1 py-2 leading-relaxed">
                Chưa có ghi chú. Ghi lại điều quan trọng ở trên, hoặc bấm "Lưu ghi chú" ngay dưới
                một câu trả lời của trợ lý.
              </p>
            ) : (
              notes.map((n) => (
                <div
                  key={n.id}
                  className="group bg-white/5 hover:bg-white/[0.08] border border-white/10 rounded-lg p-2.5 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[11px] text-slate-200 leading-relaxed break-words whitespace-pre-wrap flex-1">
                      {n.content}
                    </p>
                    <button
                      onClick={() => removeNote(n.id).catch(() => showToast('Không xoá được.', 'error'))}
                      className="p-1 rounded text-slate-500 hover:text-red-300 hover:bg-red-500/15 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-all shrink-0"
                      title="Xoá ghi chú"
                      aria-label="Xoá ghi chú"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className="text-[9px] text-slate-500 font-mono">{n.created_at}</span>
                    {n.source_message_id && (
                      <button
                        onClick={() => jumpToMessage(n.source_message_id as number)}
                        className="text-[9px] text-hds-gold/80 hover:text-hds-gold inline-flex items-center gap-0.5"
                        title="Tới câu trả lời gốc"
                      >
                        <CornerDownLeft className="w-2.5 h-2.5" />
                        Từ câu trả lời
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Chân trang */}
        <div className="p-3 border-t border-white/10 text-[11px] text-slate-400 bg-black/20">
          <div className="flex items-center gap-1.5 text-slate-300 font-medium">
            <Sparkles className="w-3.5 h-3.5 text-hds-gold" />
            <span>HDS AI Legal Core</span>
            <span className="ml-auto text-[10px] bg-white/10 text-blue-200 px-1.5 py-0.5 rounded border border-white/15">
              v1.0
            </span>
          </div>
        </div>

        {/* Nút đóng trên mobile */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="lg:hidden absolute top-2 right-2 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10"
          aria-label="Đóng bảng trợ lý"
        >
          <X className="w-4 h-4" />
        </button>
      </aside>
    </>
  );
};
