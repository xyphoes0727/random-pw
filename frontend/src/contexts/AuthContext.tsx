import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import axiosInstance from '@/lib/axios';
import { useToast } from '@/hooks/use-toast';
import {BASE_URL_HTTP,BASE_URL_WEBSOCKET} from "../config.tsx"

interface AuthContextType {
  isAuthenticated: boolean;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  signup: (username: string, email: string, password: string, password2: string, fullname?: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    const savedUsername = localStorage.getItem('username');
    if (token && savedUsername) {
      setIsAuthenticated(true);
      setUsername(savedUsername);
    }
    setLoading(false);
  }, []);

  const login = async (username: string, password: string) => {
    try {
      const response = await axiosInstance.post(`${BASE_URL_HTTP}/api/token/`, {
        username,
        password,
      });

      const { access } = response.data;
      localStorage.setItem('access_token', access);
      localStorage.setItem('username', username);
      setIsAuthenticated(true);
      setUsername(username);
      
      toast({
        title: "Login Successful",
        description: `Welcome back, ${username}!`,
      });
    } catch (error: any) {
      // Extract specific error message from backend
      let errorMessage = "Invalid credentials";
      if (error.response?.data) {
        const data = error.response.data;
        if (data.detail) {
          errorMessage = data.detail;
        } else if (data.message) {
          errorMessage = data.message;
        } else if (data.non_field_errors) {
          errorMessage = data.non_field_errors.join(', ');
        } else if (typeof data === 'string') {
          errorMessage = data;
        }
      }
      
      toast({
        title: "Login Failed",
        description: errorMessage,
        variant: "destructive",
      });
      throw error;
    }
  };

  const signup = async (username: string, email: string, password: string, password2: string, fullname?: string) => {
    if (password !== password2) {
      toast({
        title: "Signup Failed",
        description: "Passwords do not match",
        variant: "destructive",
      });
      throw new Error("Passwords do not match");
    }

    try {
      const response = await axiosInstance.post(`${BASE_URL_HTTP}/api/register/`, {
        username,
        email,
        password,
        password2,
        ...(fullname && { fullname }),
      });

      const { access } = response.data;
      localStorage.setItem('access_token', access);
      localStorage.setItem('username', username);
      setIsAuthenticated(true);
      setUsername(username);
      
      toast({
        title: "Signup Successful",
        description: `Welcome, ${username}!`,
      });
    } catch (error: any) {
      // Extract specific error message from backend
      let errorMessage = "Registration failed";
      if (error.response?.data) {
        const data = error.response.data;
        if (data.username) {
          errorMessage = `Username: ${Array.isArray(data.username) ? data.username.join(', ') : data.username}`;
        } else if (data.email) {
          errorMessage = `Email: ${Array.isArray(data.email) ? data.email.join(', ') : data.email}`;
        } else if (data.password) {
          errorMessage = `Password: ${Array.isArray(data.password) ? data.password.join(', ') : data.password}`;
        } else if (data.detail) {
          errorMessage = data.detail;
        } else if (data.message) {
          errorMessage = data.message;
        } else if (data.non_field_errors) {
          errorMessage = data.non_field_errors.join(', ');
        } else if (typeof data === 'string') {
          errorMessage = data;
        }
      }
      
      toast({
        title: "Signup Failed",
        description: errorMessage,
        variant: "destructive",
      });
      throw error;
    }
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    setIsAuthenticated(false);
    setUsername(null);
    toast({
      title: "Logged Out",
      description: "You have been successfully logged out",
    });
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, username, login, signup, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
