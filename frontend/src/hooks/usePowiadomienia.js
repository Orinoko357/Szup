import { useState, useEffect, useCallback } from 'react';
import api from '../api/axios';
import { useAuth } from './useAuth';

export function usePowiadomienia() {
  const { user } = useAuth();
  const [data, setData] = useState({ items: [], nieprzeczytane: 0 });

  const fetch = useCallback(async () => {
    if (!user) return;
    try {
      const { data: d } = await api.get('/powiadomienia');
      setData(d);
    } catch {}
  }, [user]);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 60000);
    return () => clearInterval(interval);
  }, [fetch]);

  const markRead = async (id) => {
    await api.patch(`/powiadomienia/${id}/przeczytaj`);
    fetch();
  };

  const markAllRead = async () => {
    await api.patch('/powiadomienia/przeczytaj-wszystkie');
    fetch();
  };

  return { ...data, fetch, markRead, markAllRead };
}
