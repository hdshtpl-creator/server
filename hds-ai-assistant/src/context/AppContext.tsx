import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { User, Conversation, ChatMessage, Note } from '../types';
import * as api from '../api';

interface Toast {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
}

interface AppContextType {
  // Xác thực
  token: string | null;
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  currentUser: User | null;

  // Danh sách người dùng (chỉ admin tải được)
  users: User[];
  reloadUsers: () => Promise<void>;

  // Điều hướng
  activeView: 'chat' | 'admin';
  setActiveView: (view: 'chat' | 'admin') => void;
  adminTab: string;
  setAdminTab: (tab: string) => void;

  // Cấu hình kết nối
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
  isMockMode: boolean;
  setIsMockMode: (enabled: boolean) => void;

  // Giao diện
  isDarkMode: boolean;
  toggleDarkMode: () => void;
  isSidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;

  // Hội thoại — MỖI NGƯỜI MỘT KHUNG chat bền (như Messenger), không mở mới nhiều cuộc
  activeConvId: string;
  activeConversation: Conversation | null;
  isHistoryLoading: boolean;
  addMessageToConv: (convId: string, msg: ChatMessage) => void;
  updateMessage: (msgId: string, patch: (prev: ChatMessage) => ChatMessage) => void;
  setConvServerId: (convId: string, serverId: number) => void;
  setConvTempFile: (
    convId: string,
    tempFile: { filename: string; content: string } | undefined
  ) => void;

  // Ghi chú cá nhân trong khung chat
  notes: Note[];
  reloadNotes: () => Promise<void>;
  saveNote: (content: string, sourceMessageId?: number | null) => Promise<Note>;
  removeNote: (id: number) => Promise<void>;

  // Thông báo
  toasts: Toast[];
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  removeToast: (id: string) => void;
}

const AppContext = createContext<AppContextType | null>(null);

const WELCOME_TEXT =
  'Xin chào! Tôi là Trợ lý AI của HDS Law Firm. Hãy đặt câu hỏi pháp lý hoặc tải tài liệu lên để bắt đầu tra cứu và phân tích.';

// Một người chỉ có MỘT khung chat bền. 'main' là mã cục bộ; mã thật (server_id)
// do backend cấp và được nạp cùng lịch sử khi đăng nhập.
const LOCAL_CONV_ID = 'main';

const welcomeMessage = (): ChatMessage => ({
  id: `welcome-${Date.now()}`,
  sender: 'ai',
  text: WELCOME_TEXT,
  timestamp: new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }),
});

const freshConversation = (): Conversation => ({
  id: LOCAL_CONV_ID,
  title: 'Trợ lý HDS',
  created_at: new Date().toISOString(),
  messages: [welcomeMessage()],
});

/** '2026-08-14 09:10' → '09:10' cho gọn ô tin nhắn. */
const shortTime = (iso: string): string => {
  const m = /\b(\d{1,2}:\d{2})/.exec(iso || '');
  return m ? m[1] : '';
};

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('hds_access_token'));
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  // Đang khôi phục phiên từ token đã lưu — tránh chớp màn hình đăng nhập khi tải lại trang
  const [isBootstrapping, setIsBootstrapping] = useState<boolean>(() =>
    Boolean(localStorage.getItem('hds_access_token'))
  );

  const [activeView, setActiveView] = useState<'chat' | 'admin'>('chat');
  const [adminTab, setAdminTab] = useState<string>('overview');

  const [apiBaseUrl, setApiBaseUrlState] = useState<string>(
    () => localStorage.getItem('hds_api_base_url') || api.getDefaultApiBaseUrl()
  );
  const [isMockMode, setIsMockModeState] = useState<boolean>(
    () => localStorage.getItem('hds_mock_mode') === '1'
  );

  const [isDarkMode, setIsDarkMode] = useState<boolean>(
    () => localStorage.getItem('hds_theme') === 'dark'
  );
  const [isSidebarOpen, setSidebarOpen] = useState<boolean>(false);

  const [conversation, setConversation] = useState<Conversation>(freshConversation);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);

  const [toasts, setToasts] = useState<Toast[]>([]);

  /* ---------------- Thông báo ---------------- */

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: 'success' | 'error' | 'info' = 'info') => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setToasts((prev) => [...prev, { id, type, message }]);
      setTimeout(() => removeToast(id), 5000);
    },
    [removeToast]
  );

  /* ---------------- Giao diện ---------------- */

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDarkMode);
    localStorage.setItem('hds_theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  const toggleDarkMode = useCallback(() => setIsDarkMode((prev) => !prev), []);

  /* ---------------- Cấu hình kết nối ---------------- */

  const handleSetApiBaseUrl = useCallback((url: string) => {
    setApiBaseUrlState(url);
    api.setApiBaseUrl(url);
    localStorage.setItem('hds_api_base_url', url);
  }, []);

  const handleSetIsMockMode = useCallback((enabled: boolean) => {
    setIsMockModeState(enabled);
    api.setUseMockMode(enabled);
    localStorage.setItem('hds_mock_mode', enabled ? '1' : '0');
  }, []);

  /* ---------------- Xác thực ---------------- */

  const refreshMe = useCallback(async () => {
    const me = await api.getMe();
    if (me) {
      setCurrentUser(me);
      api.setUserId(String(me.id));
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setCurrentUser(null);
    setUsers([]);
    api.setAccessToken('');
    setActiveView('chat');
    setConversation(freshConversation());
    setNotes([]);
    showToast('Đã đăng xuất khỏi hệ thống.', 'info');
  }, [showToast]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    if (!res?.access_token) {
      throw new Error('Máy chủ không trả về mã đăng nhập hợp lệ.');
    }
    setToken(res.access_token);
    if (res.user) {
      setCurrentUser(res.user);
      api.setUserId(String(res.user.id));
    }
  }, []);

  // Nạp cấu hình đã lưu vào lớp api ngay khi khởi động
  useEffect(() => {
    api.setApiBaseUrl(apiBaseUrl);
    api.setUseMockMode(isMockMode);
    if (token) api.setAccessToken(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Backend tắt giữa chừng thì api.js tự dùng dữ liệu mẫu — phải báo cho người
  // dùng biết, nếu không họ tưởng đang xem số liệu thật.
  useEffect(() => {
    api.onMockFallback((baseUrl: string) => {
      setIsMockModeState(true);
      showToast(
        `Không kết nối được backend tại ${baseUrl}. Hệ thống đang hiển thị dữ liệu giả lập.`,
        'error'
      );
    });
    return () => api.onMockFallback(null);
  }, [showToast]);

  // Khôi phục phiên: có token trong localStorage thì hỏi lại /auth/me.
  // Thiếu bước này, tải lại trang sẽ vào thẳng ứng dụng mà không biết mình là ai.
  useEffect(() => {
    if (!token) {
      setIsBootstrapping(false);
      return;
    }
    if (currentUser) return;

    let cancelled = false;
    (async () => {
      try {
        await refreshMe();
      } catch {
        if (!cancelled) {
          api.setAccessToken('');
          setToken(null);
          showToast('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.', 'info');
        }
      } finally {
        if (!cancelled) setIsBootstrapping(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const reloadUsers = useCallback(async () => {
    const fetched = await api.getUsers();
    if (Array.isArray(fetched)) setUsers(fetched);
  }, []);

  /* ---------------- Hội thoại (một khung/người) ---------------- */

  const activeConversation = conversation;

  const addMessageToConv = useCallback((_convId: string, msg: ChatMessage) => {
    setConversation((c) => ({ ...c, messages: [...c.messages, msg] }));
  }, []);

  /**
   * Sửa một tin nhắn đã có, tìm theo mã cục bộ.
   *
   * Cần cho câu trả lời chảy dần: mỗi mẩu chữ về là một lần cập nhật đúng tin
   * nhắn đó, thay vì thêm tin nhắn mới. `patch` nhận tin nhắn hiện tại để nối
   * thêm chữ vào phần đã có — dùng dạng hàm nên không bị đè khi nhiều mẩu về
   * dồn dập trong cùng một nhịp dựng hình.
   */
  const updateMessage = useCallback(
    (msgId: string, patch: (prev: ChatMessage) => ChatMessage) => {
      setConversation((c) => ({
        ...c,
        messages: c.messages.map((m) => (m.id === msgId ? patch(m) : m)),
      }));
    },
    []
  );

  const setConvServerId = useCallback((_convId: string, serverId: number) => {
    setConversation((c) => (c.server_id ? c : { ...c, server_id: serverId }));
  }, []);

  const setConvTempFile = useCallback(
    (_convId: string, tempFile: { filename: string; content: string } | undefined) => {
      setConversation((c) => ({ ...c, temp_file: tempFile }));
    },
    []
  );

  // Nạp lịch sử khung chat bền + ghi chú khi đăng nhập. Nhờ vậy tải lại trang
  // vẫn thấy nguyên mạch trao đổi, và bot hiểu được toàn bộ lịch sử.
  const reloadNotes = useCallback(async () => {
    try {
      const data = await api.getNotes();
      if (Array.isArray(data)) setNotes(data);
    } catch {
      /* im lặng — notes không phải chức năng chặn */
    }
  }, []);

  const saveNote = useCallback(
    async (content: string, sourceMessageId?: number | null): Promise<Note> => {
      const created = (await api.addNote({
        content,
        source_message_id: sourceMessageId ?? null,
      })) as Note;
      setNotes((prev) => [created, ...prev]);
      return created;
    },
    []
  );

  const removeNote = useCallback(async (id: number) => {
    await api.deleteNote(id);
    setNotes((prev) => prev.filter((n) => n.id !== id));
  }, []);

  useEffect(() => {
    if (!currentUser) return;
    let cancelled = false;
    setIsHistoryLoading(true);
    (async () => {
      try {
        const res = await api.getChatHistory();
        if (cancelled) return;
        const msgs: ChatMessage[] = (res.messages || []).map((m) => ({
          id: `h-${m.id}`,
          sender: m.role === 'user' ? 'user' : 'ai',
          text: m.content,
          timestamp: shortTime(m.created_at),
          // Mã tin nhắn thật để: nhảy tới từ ô tìm kiếm/ghi chú (cả 2 vai) và
          // gửi báo cáo (chỉ tin của AI — nút báo cáo tự lọc theo !isUser).
          serverMessageId: m.id,
        }));
        setConversation((c) => ({
          ...c,
          server_id: res.conversation_id,
          messages: msgs.length ? msgs : [welcomeMessage()],
        }));
      } catch {
        /* giữ màn chào nếu không tải được lịch sử */
      } finally {
        if (!cancelled) setIsHistoryLoading(false);
      }
    })();
    reloadNotes();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.id]);

  return (
    <AppContext.Provider
      value={{
        token,
        isAuthenticated: Boolean(token),
        isBootstrapping,
        login,
        logout,
        refreshMe,
        currentUser,
        users,
        reloadUsers,
        activeView,
        setActiveView,
        adminTab,
        setAdminTab,
        apiBaseUrl,
        setApiBaseUrl: handleSetApiBaseUrl,
        isMockMode,
        setIsMockMode: handleSetIsMockMode,
        isDarkMode,
        toggleDarkMode,
        isSidebarOpen,
        setSidebarOpen,
        activeConvId: LOCAL_CONV_ID,
        activeConversation,
        isHistoryLoading,
        addMessageToConv,
        updateMessage,
        setConvServerId,
        setConvTempFile,
        notes,
        reloadNotes,
        saveNote,
        removeNote,
        toasts,
        showToast,
        removeToast,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp phải được dùng bên trong AppProvider');
  }
  return context;
};
