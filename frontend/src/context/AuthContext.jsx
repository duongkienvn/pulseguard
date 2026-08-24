import React, { createContext, useState, useContext, useEffect } from 'react';
import axios from 'axios';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [tokens, setTokens] = useState(() => {
        const stored = localStorage.getItem('tokens');
        return stored ? JSON.parse(stored) : null;
    });

    useEffect(() => {
        if (tokens) {
            localStorage.setItem('tokens', JSON.stringify(tokens));
            // Fetch user details
            axios.get('http://localhost:8000/users/me', {
                headers: { Authorization: `Bearer ${tokens.access_token}` }
            })
                .then(res => setUser(res.data))
                .catch(() => logout());
        } else {
            localStorage.removeItem('tokens');
            setUser(null);
        }
        setLoading(false);
    }, [tokens]);

    const login = async (username, password) => {
        try {
            const res = await axios.post('http://localhost:8000/token',
                new URLSearchParams({ username, password }),
                { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
            );
            setTokens(res.data);
            return true;
        } catch (error) {
            console.error("Login failed", error);
            return false;
        }
    };

    const logout = async () => {
        if (tokens?.refresh_token) {
            try {
                await axios.post(`http://localhost:8000/logout?refresh_token=${tokens.refresh_token}`);
            } catch (e) {
                console.error("Logout failed on server", e);
            }
        }
        setTokens(null);
        setUser(null);
    };

    const register = async (username, password) => {
        try {
            await axios.post('http://localhost:8000/register', { username, password });
            return true;
        } catch (error) {
            console.error("Registration failed", error);
            return false;
        }
    }

    return (
        <AuthContext.Provider value={{ user, login, logout, register, loading, tokens }}>
            {!loading && children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
