import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { User, Conversation, ChatMessage } from '../types';
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

  // Hội thoại
  conversations: Conversation[];
  activeConvId: string;
  setActiveConvId: (id: string) => void;
  activeConversation: Conversation | null;
  createNewConversation: () => string;
  deleteConversation: (id: string) => void;
  addMessageToConv: (convId: string, msg: ChatMessage) => void;
  setConvServerId: (convId: string, serverId: number) => void;
  setConvTempFile: (
    convId: string,
    tempFile: { filename: string; content: string } | undefined
  ) => void;

  // Thông báo
  toasts: Toast[];
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  removeToast: (id: string) => void;
}

const AppContext = createContext<AppContextType | null>(null);

const WELCOME_TEXT =
  'Xin chào! Tôi là Trợ lý AI của HDS Law Firm. Hãy đặt câu hỏi pháp lý hoặc tải tài liệu lên để bắt đầu tra cứu và phân tích.';

const createConversation = (id: string): Conversation => ({
  id,
  title: 'Cuộc trò chuyện mới',
  created_at: new Date().toISOString(),
  messages: [
    {
      id: `msg-${Date.now()}`,
      sender: 'ai',
      text: WELCOME_TEXT,
      timestamp: new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }),
    },
  ],
});

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

  const [conversations, setConversations] = useState<Conversation[]>(() => [
    createConversation('conv-1'),
  ]);
  const [activeConvId, setActiveConvId] = useState<string>('conv-1');

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

  /* ---------------- Hội thoại ---------------- */

  const activeConversation =
    conversations.find((c) => c.id === activeConvId) || conversations[0] || null;

  const createNewConversation = useCallback(() => {
    const newId = `conv-${Date.now()}`;
    setConversations((prev) => [createConversation(newId), ...prev]);
    setActiveConvId(newId);
    setSidebarOpen(false);
    return newId;
  }, []);

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => {
      const remaining = prev.filter((c) => c.id !== id);
      if (remaining.length === 0) {
        const fresh = createConversation(`conv-${Date.now()}`);
        setActiveConvId(fresh.id);
        return [fresh];
      }
      setActiveConvId((current) => (current === id ? remaining[0].id : current));
      return remaining;
    });
  }, []);

  const addMessageToConv = useCallback((convId: string, msg: ChatMessage) => {
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== convId) return c;
        // Đặt tên hội thoại theo câu hỏi đầu tiên của người dùng
        const shouldRename = c.title === 'Cuộc trò chuyện mới' && msg.sender === 'user';
        const title = shouldRename
          ? msg.text.length > 40
            ? `${msg.text.slice(0, 40)}…`
            : msg.text
          : c.title;
        return { ...c, title, messages: [...c.messages, msg] };
      })
    );
  }, []);

  const setConvServerId = useCallback((convId: string, serverId: number) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === convId && !c.server_id ? { ...c, server_id: serverId } : c))
    );
  }, []);

  const setConvTempFile = useCallback(
    (convId: string, tempFile: { filename: string; content: string } | undefined) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, temp_file: tempFile } : c))
      );
    },
    []
  );

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
        conversations,
        activeConvId,
        setActiveConvId,
        activeConversation,
        createNewConversation,
        deleteConversation,
        addMessageToConv,
        setConvServerId,
        setConvTempFile,
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
