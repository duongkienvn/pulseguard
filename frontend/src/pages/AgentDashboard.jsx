import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useParams, Link } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { ArrowLeft, Activity, HardDrive, Cpu, Network, Clock, History, TrendingUp, AlertTriangle, CheckCircle, XCircle, X, Zap, ArrowUp, ArrowDown, Download } from 'lucide-react';
import axios from 'axios';

const AgentDashboard = () => {
    const { user, tokens } = useAuth();
    const { agentId } = useParams();
    const [agent, setAgent] = useState(null);
    const [metrics, setMetrics] = useState(null);
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [connected, setConnected] = useState(false);
    
    // Agent activity tracking
    const [lastSeen, setLastSeen] = useState(null);
    const [agentStatus, setAgentStatus] = useState('offline'); // 'active', 'idle', 'offline'
    
    // Detail modals
    const [showCpuModal, setShowCpuModal] = useState(false);
    const [showMemoryModal, setShowMemoryModal] = useState(false);
    const [showNetworkModal, setShowNetworkModal] = useState(false);
    const [cpuCoreHistory, setCpuCoreHistory] = useState([]);
    const [networkHistory, setNetworkHistory] = useState([]);
    
    // Historical data state
    const [historicalCpu, setHistoricalCpu] = useState([]);
    const [historicalMemory, setHistoricalMemory] = useState([]);
    const [historicalTimeRange, setHistoricalTimeRange] = useState('-5m');
    const [historicalLoading, setHistoricalLoading] = useState(false);
    const [summary, setSummary] = useState(null);
    const [activeTab, setActiveTab] = useState('realtime'); // 'realtime' or 'historical'

    // Fetch agent details
    useEffect(() => {
        const fetchAgent = async () => {
            try {
                const response = await axios.get(`http://localhost:8000/agents/${agentId}`, {
                    headers: { Authorization: `Bearer ${tokens.access_token}` }
                });
                setAgent(response.data);
            } catch (err) {
                console.error('Failed to fetch agent:', err);
                setError('Failed to load agent details');
            } finally {
                setLoading(false);
            }
        };
        fetchAgent();
    }, [agentId, tokens]);

    // Fetch historical data
    const fetchHistoricalData = async (timeRange) => {
        setHistoricalLoading(true);
        try {
            // Set appropriate aggregation interval based on time range
            const intervalMap = {
                '-5m': '10s',
                '-30m': '30s',
                '-1h': '1m',
                '-24h': '5m',
                '-7d': '30m'
            };
            const interval = intervalMap[timeRange] || '1m';
            
            const [cpuRes, memRes, summaryRes] = await Promise.all([
                axios.get(`/api/history/${agentId}/cpu?start=${timeRange}&interval=${interval}`, {
                    headers: { Authorization: `Bearer ${tokens.access_token}` }
                }),
                axios.get(`/api/history/${agentId}/memory?start=${timeRange}&interval=${interval}`, {
                    headers: { Authorization: `Bearer ${tokens.access_token}` }
                }),
                axios.get(`/api/history/${agentId}/summary?start=${timeRange}`, {
                    headers: { Authorization: `Bearer ${tokens.access_token}` }
                })
            ]);
            
            setHistoricalCpu(cpuRes.data.data.map(d => ({
                time: new Date(d.time).toLocaleString(),
                value: d.value
            })));
            
            setHistoricalMemory(memRes.data.data.map(d => ({
                time: new Date(d.time).toLocaleString(),
                value: d.value
            })));
            
            setSummary(summaryRes.data);
        } catch (err) {
            console.error('Failed to fetch historical data:', err);
        } finally {
            setHistoricalLoading(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'historical') {
            fetchHistoricalData(historicalTimeRange);
        }
    }, [activeTab, historicalTimeRange, agentId]);

    // WebSocket connection for real-time metrics
    useEffect(() => {
        if (!user || !tokens?.access_token) return;

        // Use relative WebSocket URL through nginx proxy
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${tokens.access_token}&agent_id=${agentId}`;
        console.log('Connecting to WebSocket:', wsUrl);
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket connected');
            setConnected(true);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // Only process if it matches our agent
                if (data.agent_id === parseInt(agentId)) {
                    setMetrics(data);
                    setLastSeen(Date.now());
                    setHistory(prev => {
                        const now = Date.now();
                        const thirtySecondsAgo = now - 30000;
                        const flatData = {
                            time: new Date(data.timestamp * 1000).toLocaleTimeString(),
                            timestamp: data.timestamp * 1000,
                            cpuUsage: data.cpu?.usage_percent || 0,
                            memoryUsage: data.memory?.used_percent || 0,
                        };
                        // Add new data and filter to keep only last 30 seconds
                        const newHistory = [...prev, flatData].filter(
                            item => item.timestamp >= thirtySecondsAgo
                        );
                        return newHistory;
                    });
                    
                    // Track per-core CPU history
                    if (data.cpu?.per_core_usage) {
                        setCpuCoreHistory(prev => {
                            const now = Date.now();
                            const thirtySecondsAgo = now - 30000;
                            const coreData = {
                                time: new Date(data.timestamp * 1000).toLocaleTimeString(),
                                timestamp: data.timestamp * 1000,
                                ...data.cpu.per_core_usage.reduce((acc, val, idx) => {
                                    acc[`core${idx}`] = val;
                                    return acc;
                                }, {})
                            };
                            return [...prev, coreData].filter(item => item.timestamp >= thirtySecondsAgo);
                        });
                    }
                    
                    // Track network throughput history
                    if (data.network) {
                        setNetworkHistory(prev => {
                            const now = Date.now();
                            const thirtySecondsAgo = now - 30000;
                            const netData = {
                                time: new Date(data.timestamp * 1000).toLocaleTimeString(),
                                timestamp: data.timestamp * 1000,
                                bytesSent: data.network.bytes_sent || 0,
                                bytesRecv: data.network.bytes_recv || 0,
                                packetsSent: data.network.packets_sent || 0,
                                packetsRecv: data.network.packets_recv || 0
                            };
                            const newHistory = [...prev, netData].filter(item => item.timestamp >= thirtySecondsAgo);
                            // Calculate rates (bytes per second)
                            return newHistory.map((item, idx) => {
                                if (idx === 0) return { ...item, sendRate: 0, recvRate: 0 };
                                const prevItem = newHistory[idx - 1];
                                const timeDiff = (item.timestamp - prevItem.timestamp) / 1000;
                                return {
                                    ...item,
                                    sendRate: timeDiff > 0 ? (item.bytesSent - prevItem.bytesSent) / timeDiff : 0,
                                    recvRate: timeDiff > 0 ? (item.bytesRecv - prevItem.bytesRecv) / timeDiff : 0
                                };
                            });
                        });
                    }
                }
            } catch (e) {
                console.error("Error parsing WS message", e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            setConnected(false);
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
            setConnected(false);
        };

        return () => {
            ws.close();
        };
    }, [user, agentId]);

    // Check agent activity status every second
    useEffect(() => {
        const checkActivity = () => {
            if (!lastSeen) {
                setAgentStatus('offline');
                return;
            }
            
            const now = Date.now();
            const timeSinceLastSeen = now - lastSeen;
            
            if (timeSinceLastSeen < 10000) { // Less than 10 seconds
                setAgentStatus('active');
            } else {
                setAgentStatus('offline');
            }
        };
        
        checkActivity();
        const interval = setInterval(checkActivity, 1000);
        
        return () => clearInterval(interval);
    }, [lastSeen]);

    const formatTimeSince = (timestamp) => {
        if (!timestamp) return 'Never';
        const seconds = Math.floor((Date.now() - timestamp) / 1000);
        if (seconds < 5) return 'Just now';
        if (seconds < 60) return `${seconds}s ago`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        return `${hours}h ago`;
    };

    const getStatusConfig = () => {
        switch (agentStatus) {
            case 'active':
                return {
                    icon: CheckCircle,
                    color: 'text-green-500',
                    bgColor: 'bg-green-100',
                    textColor: 'text-green-800',
                    label: 'Active',
                    pulse: true
                };
            case 'idle':
                return {
                    icon: AlertTriangle,
                    color: 'text-yellow-500',
                    bgColor: 'bg-yellow-100',
                    textColor: 'text-yellow-800',
                    label: 'Idle',
                    pulse: false
                };
            default:
                return {
                    icon: XCircle,
                    color: 'text-red-500',
                    bgColor: 'bg-red-100',
                    textColor: 'text-red-800',
                    label: 'Offline',
                    pulse: false
                };
        }
    };

    const formatBytes = (bytes) => {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    if (loading) {
        return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
    }

    if (error) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-center">
                    <p className="text-red-600 mb-4">{error}</p>
                    <Link to="/agents" className="text-indigo-600 hover:text-indigo-800">
                        Back to Agents
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <nav className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between h-16">
                        <div className="flex items-center">
                            <Link to="/agents" className="mr-4 text-gray-500 hover:text-gray-700">
                                <ArrowLeft className="h-6 w-6" />
                            </Link>
                            <Activity className="h-8 w-8 text-indigo-600" />
                            <span className="ml-2 text-xl font-bold text-gray-900">
                                {agent?.name || 'Agent Dashboard'}
                            </span>
                            {(() => {
                                const status = getStatusConfig();
                                const StatusIcon = status.icon;
                                return (
                                    <div className={`ml-3 flex items-center px-3 py-1 rounded-full ${status.bgColor}`}>
                                        <StatusIcon className={`h-4 w-4 ${status.color} ${status.pulse ? 'animate-pulse' : ''}`} />
                                        <span className={`ml-1.5 text-xs font-medium ${status.textColor}`}>
                                            {status.label}
                                        </span>
                                        {lastSeen && (
                                            <span className={`ml-2 text-xs ${status.textColor} opacity-75`}>
                                                • {formatTimeSince(lastSeen)}
                                            </span>
                                        )}
                                    </div>
                                );
                            })()}
                            <span className={`ml-2 px-2 py-1 text-xs rounded-full ${
                                connected ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
                            }`}>
                                {connected ? 'WS Connected' : 'WS Disconnected'}
                            </span>
                        </div>
                        <div className="flex items-center">
                            <span className="text-gray-700">Welcome, {user?.username}</span>
                        </div>
                    </div>
                </div>
            </nav>

            <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
                {/* Tabs */}
                <div className="mb-6 border-b border-gray-200">
                    <nav className="-mb-px flex space-x-8">
                        <button
                            onClick={() => setActiveTab('realtime')}
                            className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                activeTab === 'realtime'
                                    ? 'border-indigo-500 text-indigo-600'
                                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            }`}
                        >
                            <Activity className="inline h-4 w-4 mr-2" />
                            Real-time
                        </button>
                        <button
                            onClick={() => setActiveTab('historical')}
                            className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                activeTab === 'historical'
                                    ? 'border-indigo-500 text-indigo-600'
                                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            }`}
                        >
                            <History className="inline h-4 w-4 mr-2" />
                            Historical
                        </button>
                    </nav>
                </div>

                {activeTab === 'realtime' && (
                    <>
                        {!metrics ? (
                    <div className="text-center py-12 bg-white rounded-lg shadow">
                        <Clock className="mx-auto h-12 w-12 text-gray-400 animate-pulse" />
                        <h3 className="mt-2 text-sm font-medium text-gray-900">Waiting for metrics...</h3>
                        <p className="mt-1 text-sm text-gray-500">
                            Make sure the agent is running and connected.
                        </p>
                    </div>
                ) : (
                    <>
                        {/* Summary Cards */}
                        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 mb-8">
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <Cpu className="h-6 w-6 text-gray-400" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">CPU Usage</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {metrics.cpu?.usage_percent?.toFixed(1) || 0}%
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <Activity className="h-6 w-6 text-gray-400" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Memory Usage</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {metrics.memory?.used_percent?.toFixed(1) || 0}%
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <HardDrive className="h-6 w-6 text-gray-400" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Disk Usage</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {metrics.disk?.partitions?.[0]?.percent?.toFixed(1) || 0}%
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <Network className="h-6 w-6 text-gray-400" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Network Sent</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {formatBytes(metrics.network?.bytes_sent)}
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Network Cards Row */}
                        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3 mb-8">
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <Download className="h-6 w-6 text-green-500" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Network Received</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {formatBytes(metrics.network?.bytes_recv)}
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <ArrowUp className="h-6 w-6 text-blue-500" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Upload Speed</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {formatBytes(networkHistory.length > 1 ? networkHistory[networkHistory.length - 1]?.sendRate || 0 : 0)}/s
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="bg-white overflow-hidden shadow rounded-lg">
                                <div className="p-5">
                                    <div className="flex items-center">
                                        <div className="flex-shrink-0">
                                            <ArrowDown className="h-6 w-6 text-purple-500" />
                                        </div>
                                        <div className="ml-5 w-0 flex-1">
                                            <dl>
                                                <dt className="text-sm font-medium text-gray-500 truncate">Download Speed</dt>
                                                <dd className="text-lg font-medium text-gray-900">
                                                    {formatBytes(networkHistory.length > 1 ? networkHistory[networkHistory.length - 1]?.recvRate || 0 : 0)}/s
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Charts */}
                        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                            <div 
                                className="bg-white shadow rounded-lg p-6 cursor-pointer hover:shadow-lg transition-shadow"
                                onClick={() => setShowCpuModal(true)}
                            >
                                <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4 flex items-center justify-between">
                                    CPU History (Last 30s)
                                    <span className="text-xs text-indigo-500 font-normal">Click for details →</span>
                                </h3>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={history}>
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis 
                                                dataKey="time" 
                                                tick={{ fontSize: 11 }}
                                                interval="preserveStartEnd"
                                            />
                                            <YAxis 
                                                domain={[0, 100]} 
                                                tickFormatter={(value) => `${value}%`}
                                            />
                                            <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'CPU']} />
                                            <Legend />
                                            <Line 
                                                type="monotone" 
                                                dataKey="cpuUsage" 
                                                stroke="#8884d8" 
                                                name="CPU %" 
                                                dot={false}
                                                isAnimationActive={false}
                                                strokeWidth={2}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            <div 
                                className="bg-white shadow rounded-lg p-6 cursor-pointer hover:shadow-lg transition-shadow"
                                onClick={() => setShowMemoryModal(true)}
                            >
                                <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4 flex items-center justify-between">
                                    Memory History (Last 30s)
                                    <span className="text-xs text-green-500 font-normal">Click for details →</span>
                                </h3>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={history}>
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis 
                                                dataKey="time" 
                                                tick={{ fontSize: 11 }}
                                                interval="preserveStartEnd"
                                            />
                                            <YAxis 
                                                domain={[0, 100]} 
                                                tickFormatter={(value) => `${value}%`}
                                            />
                                            <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'Memory']} />
                                            <Legend />
                                            <Line 
                                                type="monotone" 
                                                dataKey="memoryUsage" 
                                                stroke="#82ca9d" 
                                                name="Mem %" 
                                                dot={false}
                                                isAnimationActive={false}
                                                strokeWidth={2}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        </div>

                        {/* Network Chart */}
                        <div 
                            className="mt-6 bg-white shadow rounded-lg p-6 cursor-pointer hover:shadow-lg transition-shadow"
                            onClick={() => setShowNetworkModal(true)}
                        >
                            <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4 flex items-center justify-between">
                                Network Throughput (Last 30s)
                                <span className="text-xs text-blue-500 font-normal">Click for details →</span>
                            </h3>
                            <div className="h-64">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={networkHistory.slice(1)}>
                                        <CartesianGrid strokeDasharray="3 3" />
                                        <XAxis 
                                            dataKey="time" 
                                            tick={{ fontSize: 11 }}
                                            interval="preserveStartEnd"
                                        />
                                        <YAxis 
                                            tickFormatter={(value) => formatBytes(value) + '/s'}
                                        />
                                        <Tooltip 
                                            formatter={(value, name) => [
                                                formatBytes(value) + '/s', 
                                                name === 'sendRate' ? 'Upload' : 'Download'
                                            ]} 
                                        />
                                        <Legend />
                                        <Line 
                                            type="monotone" 
                                            dataKey="sendRate" 
                                            stroke="#ff7300" 
                                            name="Upload" 
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={2}
                                        />
                                        <Line 
                                            type="monotone" 
                                            dataKey="recvRate" 
                                            stroke="#0088FE" 
                                            name="Download" 
                                            dot={false}
                                            isAnimationActive={false}
                                            strokeWidth={2}
                                        />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* System Details */}
                        <div className="mt-6 bg-white shadow rounded-lg p-6">
                            <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">System Details</h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <h4 className="font-medium text-gray-700 mb-2">Memory</h4>
                                    <div className="text-sm text-gray-600">
                                        <p>Total: {formatBytes(metrics.memory?.total)}</p>
                                        <p>Available: {formatBytes(metrics.memory?.available)}</p>
                                    </div>
                                </div>
                                <div>
                                    <h4 className="font-medium text-gray-700 mb-2">Network</h4>
                                    <div className="text-sm text-gray-600">
                                        <p>Bytes Sent: {formatBytes(metrics.network?.bytes_sent)}</p>
                                        <p>Bytes Received: {formatBytes(metrics.network?.bytes_recv)}</p>
                                    </div>
                                </div>
                                {metrics.disk?.partitions?.map((partition, idx) => (
                                    <div key={idx}>
                                        <h4 className="font-medium text-gray-700 mb-2">
                                            Disk: {partition.mountpoint}
                                        </h4>
                                        <div className="text-sm text-gray-600">
                                            <p>Total: {formatBytes(partition.total)}</p>
                                            <p>Used: {formatBytes(partition.used)} ({partition.percent}%)</p>
                                            <p>Free: {formatBytes(partition.free)}</p>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </>
                )}
                    </>
                )}

                {activeTab === 'historical' && (
                <>
                    {/* Time Range Selector */}
                    <div className="mb-6 flex items-center space-x-4">
                        <span className="text-sm font-medium text-gray-700">Time Range:</span>
                        <div className="flex space-x-2 flex-wrap gap-1">
                            {[
                                { value: '-5m', label: '5 Min' },
                                { value: '-30m', label: '30 Min' },
                                { value: '-1h', label: '1 Hour' },
                                { value: '-24h', label: '24 Hours' },
                                { value: '-7d', label: '7 Days' },
                            ].map(({ value, label }) => (
                                <button
                                    key={value}
                                    onClick={() => setHistoricalTimeRange(value)}
                                    className={`px-3 py-1 text-sm rounded-md ${
                                        historicalTimeRange === value
                                            ? 'bg-indigo-600 text-white'
                                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                                    }`}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                        <button
                            onClick={() => fetchHistoricalData(historicalTimeRange)}
                            className="ml-auto px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200"
                        >
                            Refresh
                        </button>
                    </div>

                    {historicalLoading ? (
                        <div className="text-center py-12 bg-white rounded-lg shadow">
                            <Clock className="mx-auto h-12 w-12 text-gray-400 animate-spin" />
                            <h3 className="mt-2 text-sm font-medium text-gray-900">Loading historical data...</h3>
                        </div>
                    ) : (
                        <>
                            {/* Summary Cards */}
                            {summary && (
                                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 mb-8">
                                    <div className="bg-white overflow-hidden shadow rounded-lg">
                                        <div className="p-5">
                                            <div className="flex items-center">
                                                <Cpu className="h-6 w-6 text-indigo-500" />
                                                <div className="ml-5">
                                                    <p className="text-sm font-medium text-gray-500">Avg CPU</p>
                                                    <p className="text-2xl font-semibold text-gray-900">
                                                        {summary.cpu.avg.toFixed(1)}%
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="bg-white overflow-hidden shadow rounded-lg">
                                        <div className="p-5">
                                            <div className="flex items-center">
                                                <TrendingUp className="h-6 w-6 text-red-500" />
                                                <div className="ml-5">
                                                    <p className="text-sm font-medium text-gray-500">Peak CPU</p>
                                                    <p className="text-2xl font-semibold text-gray-900">
                                                        {summary.cpu.max.toFixed(1)}%
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="bg-white overflow-hidden shadow rounded-lg">
                                        <div className="p-5">
                                            <div className="flex items-center">
                                                <Activity className="h-6 w-6 text-green-500" />
                                                <div className="ml-5">
                                                    <p className="text-sm font-medium text-gray-500">Avg Memory</p>
                                                    <p className="text-2xl font-semibold text-gray-900">
                                                        {summary.memory.avg.toFixed(1)}%
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="bg-white overflow-hidden shadow rounded-lg">
                                        <div className="p-5">
                                            <div className="flex items-center">
                                                <TrendingUp className="h-6 w-6 text-orange-500" />
                                                <div className="ml-5">
                                                    <p className="text-sm font-medium text-gray-500">Peak Memory</p>
                                                    <p className="text-2xl font-semibold text-gray-900">
                                                        {summary.memory.max.toFixed(1)}%
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Historical Charts */}
                            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                                <div className="bg-white shadow rounded-lg p-6">
                                    <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                                        CPU Usage History
                                    </h3>
                                    <div className="h-72">
                                        {historicalCpu.length > 0 ? (
                                            <ResponsiveContainer width="100%" height="100%">
                                                <AreaChart data={historicalCpu}>
                                                    <CartesianGrid strokeDasharray="3 3" />
                                                    <XAxis 
                                                        dataKey="time" 
                                                        tick={{ fontSize: 10 }}
                                                        interval="preserveStartEnd"
                                                        angle={-45}
                                                        textAnchor="end"
                                                        height={60}
                                                    />
                                                    <YAxis 
                                                        domain={[0, 100]} 
                                                        tickFormatter={(value) => `${value}%`}
                                                    />
                                                    <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'CPU']} />
                                                    <Area 
                                                        type="monotone" 
                                                        dataKey="value" 
                                                        stroke="#8884d8" 
                                                        fill="#8884d8"
                                                        fillOpacity={0.3}
                                                        name="CPU %" 
                                                    />
                                                </AreaChart>
                                            </ResponsiveContainer>
                                        ) : (
                                            <div className="h-full flex items-center justify-center text-gray-500">
                                                No historical data available
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div className="bg-white shadow rounded-lg p-6">
                                    <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">
                                        Memory Usage History
                                    </h3>
                                    <div className="h-72">
                                        {historicalMemory.length > 0 ? (
                                            <ResponsiveContainer width="100%" height="100%">
                                                <AreaChart data={historicalMemory}>
                                                    <CartesianGrid strokeDasharray="3 3" />
                                                    <XAxis 
                                                        dataKey="time" 
                                                        tick={{ fontSize: 10 }}
                                                        interval="preserveStartEnd"
                                                        angle={-45}
                                                        textAnchor="end"
                                                        height={60}
                                                    />
                                                    <YAxis 
                                                        domain={[0, 100]} 
                                                        tickFormatter={(value) => `${value}%`}
                                                    />
                                                    <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'Memory']} />
                                                    <Area 
                                                        type="monotone" 
                                                        dataKey="value" 
                                                        stroke="#82ca9d" 
                                                        fill="#82ca9d"
                                                        fillOpacity={0.3}
                                                        name="Mem %" 
                                                    />
                                                </AreaChart>
                                            </ResponsiveContainer>
                                        ) : (
                                            <div className="h-full flex items-center justify-center text-gray-500">
                                                No historical data available
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            {/* Data Points Info */}
                            {summary && (
                                <div className="mt-4 text-center text-sm text-gray-500">
                                    Based on {summary.cpu.data_points} data points
                                </div>
                            )}
                        </>
                    )}
                </>
            )}
            </main>

            {/* CPU Detail Modal */}
            {showCpuModal && metrics?.cpu && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
                        <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between">
                            <h2 className="text-xl font-bold text-gray-900 flex items-center">
                                <Cpu className="h-6 w-6 mr-2 text-indigo-600" />
                                CPU Details
                            </h2>
                            <button 
                                onClick={() => setShowCpuModal(false)}
                                className="text-gray-400 hover:text-gray-600"
                            >
                                <X className="h-6 w-6" />
                            </button>
                        </div>
                        
                        <div className="p-6">
                            {/* Overall CPU */}
                            <div className="mb-6">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm font-medium text-gray-700">Overall CPU Usage</span>
                                    <span className="text-2xl font-bold text-indigo-600">
                                        {metrics.cpu.usage_percent?.toFixed(1)}%
                                    </span>
                                </div>
                                <div className="w-full bg-gray-200 rounded-full h-4">
                                    <div 
                                        className="bg-indigo-600 h-4 rounded-full transition-all duration-300"
                                        style={{ width: `${metrics.cpu.usage_percent || 0}%` }}
                                    />
                                </div>
                            </div>

                            {/* CPU Frequency */}
                            {metrics.cpu.freq && (
                                <div className="mb-6 p-4 bg-gray-50 rounded-lg">
                                    <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                                        <Zap className="h-4 w-4 mr-2 text-yellow-500" />
                                        CPU Frequency
                                    </h3>
                                    <div className="grid grid-cols-3 gap-4 text-center">
                                        <div>
                                            <p className="text-xs text-gray-500">Current</p>
                                            <p className="text-lg font-semibold text-gray-900">
                                                {metrics.cpu.freq.current?.toFixed(0) || 'N/A'} MHz
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-gray-500">Min</p>
                                            <p className="text-lg font-semibold text-gray-900">
                                                {metrics.cpu.freq.min?.toFixed(0) || 'N/A'} MHz
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-gray-500">Max</p>
                                            <p className="text-lg font-semibold text-gray-900">
                                                {metrics.cpu.freq.max?.toFixed(0) || 'N/A'} MHz
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Per-Core Usage */}
                            {metrics.cpu.per_core_usage && metrics.cpu.per_core_usage.length > 0 && (
                                <div className="mb-6">
                                    <h3 className="text-sm font-medium text-gray-700 mb-3">
                                        Per-Core Usage ({metrics.cpu.per_core_usage.length} cores)
                                    </h3>
                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                        {metrics.cpu.per_core_usage.map((usage, idx) => (
                                            <div key={idx} className="bg-gray-50 rounded-lg p-3">
                                                <div className="flex items-center justify-between mb-1">
                                                    <span className="text-xs text-gray-500">Core {idx}</span>
                                                    <span className="text-sm font-semibold text-gray-900">
                                                        {usage?.toFixed(1)}%
                                                    </span>
                                                </div>
                                                <div className="w-full bg-gray-200 rounded-full h-2">
                                                    <div 
                                                        className={`h-2 rounded-full transition-all duration-300 ${
                                                            usage > 80 ? 'bg-red-500' : 
                                                            usage > 50 ? 'bg-yellow-500' : 'bg-green-500'
                                                        }`}
                                                        style={{ width: `${usage || 0}%` }}
                                                    />
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Per-Core History Chart */}
                            {cpuCoreHistory.length > 0 && metrics.cpu.per_core_usage && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-700 mb-3">
                                        Per-Core History (Last 30s)
                                    </h3>
                                    <div className="h-64">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <LineChart data={cpuCoreHistory}>
                                                <CartesianGrid strokeDasharray="3 3" />
                                                <XAxis 
                                                    dataKey="time" 
                                                    tick={{ fontSize: 10 }}
                                                    interval="preserveStartEnd"
                                                />
                                                <YAxis 
                                                    domain={[0, 100]} 
                                                    tickFormatter={(value) => `${value}%`}
                                                />
                                                <Tooltip 
                                                    formatter={(value, name) => [
                                                        `${Number(value).toFixed(1)}%`, 
                                                        name.replace('core', 'Core ')
                                                    ]} 
                                                />
                                                <Legend />
                                                {metrics.cpu.per_core_usage.map((_, idx) => {
                                                    const colors = [
                                                        '#8884d8', '#82ca9d', '#ffc658', '#ff7300',
                                                        '#00C49F', '#FFBB28', '#FF8042', '#0088FE',
                                                        '#a4de6c', '#d0ed57', '#ffc0cb', '#dda0dd'
                                                    ];
                                                    return (
                                                        <Line 
                                                            key={idx}
                                                            type="monotone" 
                                                            dataKey={`core${idx}`}
                                                            stroke={colors[idx % colors.length]}
                                                            name={`Core ${idx}`}
                                                            dot={false}
                                                            isAnimationActive={false}
                                                            strokeWidth={1.5}
                                                        />
                                                    );
                                                })}
                                            </LineChart>
                                        </ResponsiveContainer>
                                    </div>
                                </div>
                            )}

                            {/* CPU Info */}
                            <div className="mt-6 pt-4 border-t text-sm text-gray-500">
                                <div className="flex justify-between">
                                    <span>Physical Cores: {metrics.cpu.count || 'N/A'}</span>
                                    <span>Logical Cores: {metrics.cpu.count_logical || 'N/A'}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Memory Detail Modal */}
            {showMemoryModal && metrics?.memory && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
                        <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between">
                            <h2 className="text-xl font-bold text-gray-900 flex items-center">
                                <Activity className="h-6 w-6 mr-2 text-green-600" />
                                Memory Details
                            </h2>
                            <button 
                                onClick={() => setShowMemoryModal(false)}
                                className="text-gray-400 hover:text-gray-600"
                            >
                                <X className="h-6 w-6" />
                            </button>
                        </div>
                        
                        <div className="p-6">
                            {/* Overall Memory Usage */}
                            <div className="mb-6">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm font-medium text-gray-700">Memory Usage</span>
                                    <span className="text-2xl font-bold text-green-600">
                                        {metrics.memory.used_percent?.toFixed(1)}%
                                    </span>
                                </div>
                                <div className="w-full bg-gray-200 rounded-full h-4">
                                    <div 
                                        className="bg-green-500 h-4 rounded-full transition-all duration-300"
                                        style={{ width: `${metrics.memory.used_percent || 0}%` }}
                                    />
                                </div>
                            </div>

                            {/* Memory Breakdown */}
                            <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Total</p>
                                    <p className="text-lg font-semibold text-gray-900">
                                        {formatBytes(metrics.memory.total)}
                                    </p>
                                </div>
                                <div className="bg-green-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Used</p>
                                    <p className="text-lg font-semibold text-green-700">
                                        {formatBytes(metrics.memory.used)}
                                    </p>
                                </div>
                                <div className="bg-blue-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Available</p>
                                    <p className="text-lg font-semibold text-blue-700">
                                        {formatBytes(metrics.memory.available)}
                                    </p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Free</p>
                                    <p className="text-lg font-semibold text-gray-700">
                                        {formatBytes(metrics.memory.free)}
                                    </p>
                                </div>
                            </div>

                            {/* Visual Memory Bar */}
                            <div className="mb-6">
                                <h3 className="text-sm font-medium text-gray-700 mb-3">Memory Distribution</h3>
                                <div className="w-full h-8 bg-gray-200 rounded-lg overflow-hidden flex">
                                    <div 
                                        className="bg-green-500 h-full flex items-center justify-center text-xs text-white font-medium"
                                        style={{ width: `${((metrics.memory.used || 0) / (metrics.memory.total || 1)) * 100}%` }}
                                    >
                                        {((metrics.memory.used || 0) / (metrics.memory.total || 1) * 100).toFixed(0)}% Used
                                    </div>
                                    <div 
                                        className="bg-blue-400 h-full flex items-center justify-center text-xs text-white font-medium"
                                        style={{ width: `${(((metrics.memory.available || 0) - (metrics.memory.free || 0)) / (metrics.memory.total || 1)) * 100}%` }}
                                    >
                                    </div>
                                    <div 
                                        className="bg-gray-300 h-full flex items-center justify-center text-xs text-gray-600 font-medium"
                                        style={{ width: `${((metrics.memory.free || 0) / (metrics.memory.total || 1)) * 100}%` }}
                                    >
                                    </div>
                                </div>
                                <div className="flex justify-between mt-2 text-xs text-gray-500">
                                    <span className="flex items-center"><span className="w-3 h-3 bg-green-500 rounded mr-1"></span>Used</span>
                                    <span className="flex items-center"><span className="w-3 h-3 bg-blue-400 rounded mr-1"></span>Cached/Buffers</span>
                                    <span className="flex items-center"><span className="w-3 h-3 bg-gray-300 rounded mr-1"></span>Free</span>
                                </div>
                            </div>

                            {/* Memory History Chart */}
                            <div>
                                <h3 className="text-sm font-medium text-gray-700 mb-3">
                                    Memory Usage History (Last 30s)
                                </h3>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <AreaChart data={history}>
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis 
                                                dataKey="time" 
                                                tick={{ fontSize: 10 }}
                                                interval="preserveStartEnd"
                                            />
                                            <YAxis 
                                                domain={[0, 100]} 
                                                tickFormatter={(value) => `${value}%`}
                                            />
                                            <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Memory']} />
                                            <Area 
                                                type="monotone" 
                                                dataKey="memoryUsage" 
                                                stroke="#82ca9d"
                                                fill="#82ca9d"
                                                fillOpacity={0.3}
                                                name="Memory %"
                                                isAnimationActive={false}
                                            />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Swap Info (if available) */}
                            {metrics.memory.swap_total > 0 && (
                                <div className="mt-6 pt-4 border-t">
                                    <h3 className="text-sm font-medium text-gray-700 mb-3">Swap Memory</h3>
                                    <div className="grid grid-cols-3 gap-4 text-sm">
                                        <div>
                                            <p className="text-gray-500">Total</p>
                                            <p className="font-semibold">{formatBytes(metrics.memory.swap_total)}</p>
                                        </div>
                                        <div>
                                            <p className="text-gray-500">Used</p>
                                            <p className="font-semibold">{formatBytes(metrics.memory.swap_used)}</p>
                                        </div>
                                        <div>
                                            <p className="text-gray-500">Free</p>
                                            <p className="font-semibold">{formatBytes(metrics.memory.swap_free)}</p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Network Detail Modal */}
            {showNetworkModal && metrics?.network && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
                        <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between">
                            <h2 className="text-xl font-bold text-gray-900 flex items-center">
                                <Network className="h-6 w-6 mr-2 text-blue-600" />
                                Network Details
                            </h2>
                            <button 
                                onClick={() => setShowNetworkModal(false)}
                                className="text-gray-400 hover:text-gray-600"
                            >
                                <X className="h-6 w-6" />
                            </button>
                        </div>
                        
                        <div className="p-6">
                            {/* Current Throughput */}
                            {networkHistory.length > 1 && (
                                <div className="mb-6 grid grid-cols-2 gap-4">
                                    <div className="bg-orange-50 rounded-lg p-4">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <p className="text-xs text-orange-600 mb-1">Upload Speed</p>
                                                <p className="text-2xl font-bold text-orange-700">
                                                    {formatBytes(networkHistory[networkHistory.length - 1]?.sendRate || 0)}/s
                                                </p>
                                            </div>
                                            <div className="text-orange-400">
                                                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 11l5-5m0 0l5 5m-5-5v12" />
                                                </svg>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="bg-blue-50 rounded-lg p-4">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <p className="text-xs text-blue-600 mb-1">Download Speed</p>
                                                <p className="text-2xl font-bold text-blue-700">
                                                    {formatBytes(networkHistory[networkHistory.length - 1]?.recvRate || 0)}/s
                                                </p>
                                            </div>
                                            <div className="text-blue-400">
                                                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 13l-5 5m0 0l-5-5m5 5V6" />
                                                </svg>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Total Data Transferred */}
                            <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Total Sent</p>
                                    <p className="text-lg font-semibold text-orange-600">
                                        {formatBytes(metrics.network.bytes_sent)}
                                    </p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Total Received</p>
                                    <p className="text-lg font-semibold text-blue-600">
                                        {formatBytes(metrics.network.bytes_recv)}
                                    </p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Packets Sent</p>
                                    <p className="text-lg font-semibold text-gray-700">
                                        {(metrics.network.packets_sent || 0).toLocaleString()}
                                    </p>
                                </div>
                                <div className="bg-gray-50 rounded-lg p-4 text-center">
                                    <p className="text-xs text-gray-500 mb-1">Packets Received</p>
                                    <p className="text-lg font-semibold text-gray-700">
                                        {(metrics.network.packets_recv || 0).toLocaleString()}
                                    </p>
                                </div>
                            </div>

                            {/* Network Throughput Chart */}
                            <div className="mb-6">
                                <h3 className="text-sm font-medium text-gray-700 mb-3">
                                    Network Throughput (Last 30s)
                                </h3>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <AreaChart data={networkHistory.slice(1)}>
                                            <CartesianGrid strokeDasharray="3 3" />
                                            <XAxis 
                                                dataKey="time" 
                                                tick={{ fontSize: 10 }}
                                                interval="preserveStartEnd"
                                            />
                                            <YAxis 
                                                tickFormatter={(value) => formatBytes(value) + '/s'}
                                            />
                                            <Tooltip 
                                                formatter={(value, name) => [
                                                    formatBytes(value) + '/s', 
                                                    name === 'sendRate' ? 'Upload' : 'Download'
                                                ]} 
                                            />
                                            <Legend />
                                            <Area 
                                                type="monotone" 
                                                dataKey="sendRate" 
                                                stroke="#ff7300"
                                                fill="#ff7300"
                                                fillOpacity={0.3}
                                                name="Upload"
                                                isAnimationActive={false}
                                            />
                                            <Area 
                                                type="monotone" 
                                                dataKey="recvRate" 
                                                stroke="#0088FE"
                                                fill="#0088FE"
                                                fillOpacity={0.3}
                                                name="Download"
                                                isAnimationActive={false}
                                            />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>

                            {/* Error Stats */}
                            {(metrics.network.errin > 0 || metrics.network.errout > 0 || metrics.network.dropin > 0 || metrics.network.dropout > 0) && (
                                <div className="pt-4 border-t">
                                    <h3 className="text-sm font-medium text-gray-700 mb-3 flex items-center">
                                        <AlertTriangle className="h-4 w-4 mr-2 text-yellow-500" />
                                        Network Errors & Drops
                                    </h3>
                                    <div className="grid grid-cols-4 gap-4 text-sm">
                                        <div className="text-center">
                                            <p className="text-gray-500">Errors In</p>
                                            <p className="font-semibold text-red-600">{metrics.network.errin || 0}</p>
                                        </div>
                                        <div className="text-center">
                                            <p className="text-gray-500">Errors Out</p>
                                            <p className="font-semibold text-red-600">{metrics.network.errout || 0}</p>
                                        </div>
                                        <div className="text-center">
                                            <p className="text-gray-500">Drops In</p>
                                            <p className="font-semibold text-yellow-600">{metrics.network.dropin || 0}</p>
                                        </div>
                                        <div className="text-center">
                                            <p className="text-gray-500">Drops Out</p>
                                            <p className="font-semibold text-yellow-600">{metrics.network.dropout || 0}</p>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Connection Info */}
                            <div className="mt-6 pt-4 border-t text-sm text-gray-500">
                                <p>Network statistics since system boot. Throughput calculated from real-time data stream.</p>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default AgentDashboard;
