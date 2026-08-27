import React, { useEffect, useState, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { Link } from 'react-router-dom';
import { Activity, Plus, Trash2, Copy, RefreshCw, Eye, EyeOff, Monitor, Clock, AlertTriangle, CheckCircle } from 'lucide-react';
import axios from 'axios';

const Agents = () => {
    const { user, logout, tokens } = useAuth();
    const [agents, setAgents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showNewAgentForm, setShowNewAgentForm] = useState(false);
    const [newAgentName, setNewAgentName] = useState('');
    const [createdAgent, setCreatedAgent] = useState(null);
    const [visibleTokens, setVisibleTokens] = useState({});
    const [error, setError] = useState('');
    const [tokenTimeRemaining, setTokenTimeRemaining] = useState(null);

    const fetchAgents = useCallback(async () => {
        try {
            const response = await axios.get('http://localhost:8000/agents', {
                headers: { Authorization: `Bearer ${tokens.access_token}` }
            });
            setAgents(response.data);
        } catch (err) {
            console.error('Failed to fetch agents:', err);
            setError('Failed to load agents');
        } finally {
            setLoading(false);
        }
    }, [tokens]);

    // Initial fetch and periodic polling for status updates
    useEffect(() => {
        fetchAgents();
        
        // Poll every 5 seconds to catch status changes (pending -> active)
        const pollInterval = setInterval(() => {
            fetchAgents();
        }, 5000);
        
        return () => clearInterval(pollInterval);
    }, [fetchAgents]);

    // Countdown timer for token expiration
    useEffect(() => {
        if (!createdAgent?.token_expires_at || createdAgent?.token_activated) {
            setTokenTimeRemaining(null);
            return;
        }

        const calculateTimeRemaining = () => {
            // Server returns UTC timestamp without 'Z', so append it
            const expiresAtStr = createdAgent.token_expires_at.endsWith('Z') 
                ? createdAgent.token_expires_at 
                : createdAgent.token_expires_at + 'Z';
            const expiresAt = new Date(expiresAtStr).getTime();
            const now = Date.now();
            const diff = Math.max(0, Math.floor((expiresAt - now) / 1000));
            return diff;
        };

        setTokenTimeRemaining(calculateTimeRemaining());

        const interval = setInterval(() => {
            const remaining = calculateTimeRemaining();
            setTokenTimeRemaining(remaining);
            
            if (remaining <= 0) {
                clearInterval(interval);
            }
        }, 1000);

        return () => clearInterval(interval);
    }, [createdAgent]);

    const formatTimeRemaining = (seconds) => {
        if (seconds === null) return '';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    const getTimerColor = (seconds) => {
        if (seconds === null) return '';
        if (seconds <= 0) return 'text-red-600';
        if (seconds <= 60) return 'text-red-500';
        if (seconds <= 120) return 'text-yellow-500';
        return 'text-green-500';
    };

    const createAgent = async (e) => {
        e.preventDefault();
        if (!newAgentName.trim()) return;

        try {
            const response = await axios.post(
                'http://localhost:8000/agents',
                { name: newAgentName },
                { headers: { Authorization: `Bearer ${tokens.access_token}` } }
            );
            setCreatedAgent(response.data);
            setNewAgentName('');
            // Don't close the modal - we'll show the token in it instead
            fetchAgents();
        } catch (err) {
            console.error('Failed to create agent:', err);
            setError('Failed to create agent');
        }
    };

    const closeAgentModal = () => {
        setShowNewAgentForm(false);
        setCreatedAgent(null);
        setNewAgentName('');
    };

    const deleteAgent = async (agentId) => {
        if (!confirm('Are you sure you want to delete this agent?')) return;

        try {
            await axios.delete(`http://localhost:8000/agents/${agentId}`, {
                headers: { Authorization: `Bearer ${tokens.access_token}` }
            });
            fetchAgents();
        } catch (err) {
            console.error('Failed to delete agent:', err);
            setError('Failed to delete agent');
        }
    };

    const regenerateToken = async (agentId) => {
        if (!confirm('Are you sure you want to regenerate the token? The old token will stop working.')) return;

        try {
            const response = await axios.post(
                `http://localhost:8000/agents/${agentId}/regenerate-token`,
                {},
                { headers: { Authorization: `Bearer ${tokens.access_token}` } }
            );
            setCreatedAgent(response.data);
            setShowNewAgentForm(true); // Show the modal with the new token
            fetchAgents();
        } catch (err) {
            console.error('Failed to regenerate token:', err);
            setError('Failed to regenerate token');
        }
    };

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text);
    };

    const toggleTokenVisibility = (agentId) => {
        setVisibleTokens(prev => ({
            ...prev,
            [agentId]: !prev[agentId]
        }));
    };

    const formatDate = (dateString) => {
        if (!dateString) return 'Never';
        return new Date(dateString).toLocaleString();
    };

    const getStatusColor = (lastSeen) => {
        if (!lastSeen) return 'bg-gray-400';
        const diff = Date.now() - new Date(lastSeen).getTime();
        if (diff < 60000) return 'bg-green-500'; // Less than 1 minute
        if (diff < 300000) return 'bg-yellow-500'; // Less than 5 minutes
        return 'bg-red-500';
    };

    if (loading) {
        return <div className="min-h-screen flex items-center justify-center">Loading agents...</div>;
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <nav className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between h-16">
                        <div className="flex items-center">
                            <Link to="/agents" className="flex items-center">
                                <Activity className="h-8 w-8 text-indigo-600" />
                                <span className="ml-2 text-xl font-bold text-gray-900">StatusMonitor</span>
                            </Link>
                            <div className="ml-10 flex items-baseline space-x-4">
                                <Link to="/agents" className="text-gray-900 px-3 py-2 rounded-md text-sm font-medium">Agents</Link>
                                <Link to="/alerts" className="text-gray-500 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium">Alerts</Link>
                            </div>
                        </div>
                        <div className="flex items-center space-x-4">
                            <span className="text-gray-700">Welcome, {user?.username}</span>
                            <button
                                onClick={logout}
                                className="px-3 py-2 text-sm font-medium text-gray-700 hover:text-gray-900"
                            >
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </nav>

            <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
                <div className="flex justify-between items-center mb-6">
                    <h1 className="text-2xl font-bold text-gray-900">My Agents</h1>
                    <button
                        onClick={() => setShowNewAgentForm(true)}
                        className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
                    >
                        <Plus className="h-4 w-4 mr-2" />
                        New Agent
                    </button>
                </div>

                {error && (
                    <div className="mb-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded">
                        {error}
                        <button onClick={() => setError('')} className="ml-2 font-bold">×</button>
                    </div>
                )}

                {/* New Agent Form Modal */}
                {showNewAgentForm && (
                    <div className="fixed inset-0 bg-gray-600 bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-white rounded-lg p-6 w-full max-w-md">
                            {!createdAgent ? (
                                <>
                                    <h2 className="text-lg font-bold mb-4">Create New Agent</h2>
                                    <form onSubmit={createAgent}>
                                        <div className="mb-4">
                                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                                Agent Name
                                            </label>
                                            <input
                                                type="text"
                                                value={newAgentName}
                                                onChange={(e) => setNewAgentName(e.target.value)}
                                                placeholder="e.g., My Desktop, Work Laptop"
                                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                required
                                            />
                                        </div>
                                        <div className="flex justify-end space-x-2">
                                            <button
                                                type="button"
                                                onClick={closeAgentModal}
                                                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
                                            >
                                                Cancel
                                            </button>
                                            <button
                                                type="submit"
                                                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
                                            >
                                                Create
                                            </button>
                                        </div>
                                    </form>
                                </>
                            ) : (
                                <>
                                    <div className="text-center mb-4">
                                        {createdAgent.token_activated ? (
                                            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
                                                <CheckCircle className="h-6 w-6 text-green-600" />
                                            </div>
                                        ) : tokenTimeRemaining !== null && tokenTimeRemaining <= 0 ? (
                                            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100 mb-4">
                                                <AlertTriangle className="h-6 w-6 text-red-600" />
                                            </div>
                                        ) : (
                                            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
                                                <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                                </svg>
                                            </div>
                                        )}
                                        <h2 className="text-lg font-bold text-gray-900">
                                            {createdAgent.token_activated 
                                                ? 'Agent Active!' 
                                                : tokenTimeRemaining <= 0 
                                                    ? 'Token Expired!' 
                                                    : 'Agent Created Successfully!'}
                                        </h2>
                                        <p className="text-sm text-gray-600 mt-1">"{createdAgent.name}"</p>
                                    </div>
                                    
                                    {/* Token Expiration Timer */}
                                    {!createdAgent.token_activated && tokenTimeRemaining !== null && (
                                        <div className={`mb-4 p-4 rounded-lg border ${
                                            tokenTimeRemaining <= 0 
                                                ? 'bg-red-50 border-red-200' 
                                                : tokenTimeRemaining <= 60 
                                                    ? 'bg-red-50 border-red-200' 
                                                    : tokenTimeRemaining <= 120 
                                                        ? 'bg-yellow-50 border-yellow-200' 
                                                        : 'bg-blue-50 border-blue-200'
                                        }`}>
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center">
                                                    <Clock className={`h-5 w-5 mr-2 ${getTimerColor(tokenTimeRemaining)}`} />
                                                    <span className="text-sm font-medium">
                                                        {tokenTimeRemaining <= 0 
                                                            ? 'Token has expired!' 
                                                            : 'Token expires in:'}
                                                    </span>
                                                </div>
                                                {tokenTimeRemaining > 0 && (
                                                    <span className={`text-2xl font-bold font-mono ${getTimerColor(tokenTimeRemaining)}`}>
                                                        {formatTimeRemaining(tokenTimeRemaining)}
                                                    </span>
                                                )}
                                            </div>
                                            {tokenTimeRemaining <= 0 && (
                                                <p className="text-sm text-red-600 mt-2">
                                                    Click "Regenerate Token" from the agents list to get a new token.
                                                </p>
                                            )}
                                            {tokenTimeRemaining > 0 && (
                                                <p className="text-xs text-gray-500 mt-2">
                                                    Configure your agent before the timer expires. Once activated, the token works permanently.
                                                </p>
                                            )}
                                        </div>
                                    )}

                                    {createdAgent.token_activated && (
                                        <div className="mb-4 p-4 rounded-lg bg-green-50 border border-green-200">
                                            <div className="flex items-center">
                                                <CheckCircle className="h-5 w-5 mr-2 text-green-600" />
                                                <span className="text-sm font-medium text-green-800">
                                                    Token activated! Agent is connected and working.
                                                </span>
                                            </div>
                                        </div>
                                    )}
                                    
                                    {tokenTimeRemaining > 0 && !createdAgent.token_activated && (
                                        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4">
                                            <h3 className="font-semibold text-yellow-800 mb-2">⚠️ Important: Save Your Token</h3>
                                            <p className="text-sm text-yellow-700 mb-3">
                                                Copy this token and configure your agent <strong>within 5 minutes</strong>. Once activated, it works permanently.
                                            </p>
                                            <div className="bg-white border border-yellow-300 rounded p-3">
                                                <code className="text-xs font-mono break-all text-gray-800 select-all">
                                                    {createdAgent.token}
                                                </code>
                                            </div>
                                            <button
                                                onClick={() => copyToClipboard(createdAgent.token)}
                                                className="mt-3 w-full flex items-center justify-center px-4 py-2 bg-yellow-100 text-yellow-800 rounded-md hover:bg-yellow-200 transition-colors"
                                            >
                                                <Copy className="h-4 w-4 mr-2" />
                                                Copy Token to Clipboard
                                            </button>
                                        </div>
                                    )}

                                    {tokenTimeRemaining > 0 && !createdAgent.token_activated && (
                                        <div className="bg-gray-50 rounded-lg p-4 mb-4">
                                            <h4 className="font-medium text-gray-700 mb-2">Quick Start:</h4>
                                            <code className="text-xs bg-gray-100 p-2 rounded block overflow-x-auto">
                                                AGENT_TOKEN={createdAgent.token.substring(0, 20)}... python agent_service/main.py
                                            </code>
                                        </div>
                                    )}

                                    <button
                                        onClick={closeAgentModal}
                                        className="w-full px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
                                    >
                                        {createdAgent.token_activated ? 'Close' : tokenTimeRemaining <= 0 ? 'Close' : "I've Saved the Token - Close"}
                                    </button>
                                </>
                            )}
                        </div>
                    </div>
                )}

                {/* Agents List */}
                {agents.length === 0 ? (
                    <div className="text-center py-12 bg-white rounded-lg shadow">
                        <Monitor className="mx-auto h-12 w-12 text-gray-400" />
                        <h3 className="mt-2 text-sm font-medium text-gray-900">No agents</h3>
                        <p className="mt-1 text-sm text-gray-500">
                            Get started by creating a new agent.
                        </p>
                    </div>
                ) : (
                    <div className="bg-white shadow overflow-hidden rounded-lg">
                        <ul className="divide-y divide-gray-200">
                            {agents.map((agent) => (
                                <li key={agent.id} className="p-4 hover:bg-gray-50">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center space-x-4">
                                            <div className={`h-3 w-3 rounded-full ${getStatusColor(agent.last_seen)}`} />
                                            <div>
                                                <div className="flex items-center space-x-2">
                                                    <Link
                                                        to={`/agents/${agent.id}`}
                                                        className="text-lg font-medium text-indigo-600 hover:text-indigo-800"
                                                    >
                                                        {agent.name}
                                                    </Link>
                                                    {agent.token_activated ? (
                                                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                                                            <CheckCircle className="h-3 w-3 mr-1" />
                                                            Active
                                                        </span>
                                                    ) : (
                                                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">
                                                            <AlertTriangle className="h-3 w-3 mr-1" />
                                                            Pending Activation
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="flex items-center text-sm text-gray-500 mt-1">
                                                    <Clock className="h-4 w-4 mr-1" />
                                                    Last seen: {formatDate(agent.last_seen)}
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex items-center space-x-2">
                                            <Link
                                                to={`/agents/${agent.id}`}
                                                className="p-2 text-gray-400 hover:text-indigo-600"
                                                title="View Dashboard"
                                            >
                                                <Activity className="h-5 w-5" />
                                            </Link>
                                            <button
                                                onClick={() => regenerateToken(agent.id)}
                                                className="p-2 text-gray-400 hover:text-yellow-600"
                                                title="Regenerate Token"
                                            >
                                                <RefreshCw className="h-5 w-5" />
                                            </button>
                                            <button
                                                onClick={() => deleteAgent(agent.id)}
                                                className="p-2 text-gray-400 hover:text-red-600"
                                                title="Delete Agent"
                                            >
                                                <Trash2 className="h-5 w-5" />
                                            </button>
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </main>
        </div>
    );
};

export default Agents;
