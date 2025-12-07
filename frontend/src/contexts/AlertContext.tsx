import { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import { useToast } from '@/hooks/use-toast';
import { BASE_URL_WEBSOCKET } from '../config';

interface AlertResult {
  id: string;
  summary: string;
  cause: string;
  category: string;
  timestamp: number;
}

interface AlertContextType {
  alerts: AlertResult[];
  unreadCount: number;
  markAllAsRead: () => void;
  clearAlerts: () => void;
}

const AlertContext = createContext<AlertContextType | undefined>(undefined);

// Use port 8124 for alerts WebSocket as specified
const ALERTS_WEBSOCKET_URL = 'ws://localhost:8124/ws/alerts';

export const AlertProvider = ({ children }: { children: ReactNode }) => {
  const [alerts, setAlerts] = useState<AlertResult[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { toast } = useToast();

  // Load alerts from sessionStorage on mount
  useEffect(() => {
    try {
      const storedAlerts = sessionStorage.getItem('system-alerts');
      if (storedAlerts) {
        const parsed = JSON.parse(storedAlerts);
        setAlerts(parsed);
        setUnreadCount(parsed.length);
      }
    } catch (error) {
      console.error('Error loading alerts from sessionStorage:', error);
    }
  }, []);

  // Save alerts to sessionStorage whenever they change
  useEffect(() => {
    if (alerts.length > 0) {
      try {
        sessionStorage.setItem('system-alerts', JSON.stringify(alerts));
      } catch (error) {
        console.error('Error saving alerts to sessionStorage:', error);
      }
    }
  }, [alerts]);

  // Connect to alerts WebSocket
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        console.log('🔔 Connecting to alerts WebSocket...');
        const ws = new WebSocket(ALERTS_WEBSOCKET_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log('🔔 Alerts WebSocket connected');
        };

        ws.onmessage = (event) => {
          try {
            const response = JSON.parse(event.data);
            console.log('🔔 Received alert:', response);

            if (response.type === 'alert_result' && response.result) {
              const newAlert: AlertResult = {
                id: `alert-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                summary: response.result.summary || 'Unknown alert',
                cause: response.result.cause || 'Unknown cause',
                category: response.result.category || 'Unknown',
                timestamp: Date.now(),
              };

              setAlerts(prev => [newAlert, ...prev].slice(0, 100)); // Keep max 100 alerts
              setUnreadCount(prev => prev + 1);

              // Show toast notification
              const truncatedCause = newAlert.cause.length > 80 
                ? `${newAlert.cause.substring(0, 80)}...` 
                : newAlert.cause;

              toast({
                title: `⚠️ ${newAlert.category}`,
                description: truncatedCause,
                variant: "destructive",
                duration: 5000,
              });
            }
          } catch (error) {
            console.error('Error parsing alert message:', error);
          }
        };

        ws.onerror = (error) => {
          console.error('Alerts WebSocket error:', error);
        };

        ws.onclose = () => {
          console.log('🔔 Alerts WebSocket disconnected');
          wsRef.current = null;

          // Reconnect after 5 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('🔔 Attempting to reconnect to alerts WebSocket...');
            connectWebSocket();
          }, 5000);
        };
      } catch (error) {
        console.error('Error creating alerts WebSocket:', error);
      }
    };

    connectWebSocket();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [toast]);

  const markAllAsRead = () => {
    setUnreadCount(0);
  };

  const clearAlerts = () => {
    setAlerts([]);
    setUnreadCount(0);
    sessionStorage.removeItem('system-alerts');
  };

  return (
    <AlertContext.Provider value={{ alerts, unreadCount, markAllAsRead, clearAlerts }}>
      {children}
    </AlertContext.Provider>
  );
};

export const useAlerts = () => {
  const context = useContext(AlertContext);
  if (context === undefined) {
    throw new Error('useAlerts must be used within an AlertProvider');
  }
  return context;
};
