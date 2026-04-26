// =============================================================
//  Live Auto Subtitle System — Flutter Mobile App
//  main.dart  ·  Full-featured subtitle display with dark UI
// =============================================================

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:socket_io_client/socket_io_client.dart' as IO;

// ── Server address ────────────────────────────────────────
// Running on Chrome/Windows on the same machine → use localhost
// Running on a real Android/iOS device → replace with your LAN IP
//   e.g. '192.168.1.100'  (find it with: ipconfig)
const String SERVER_IP   = 'localhost';
const int    SERVER_PORT = 3000;

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // Portrait lock — mobile only (not supported on web/Windows)
  if (!kIsWeb) {
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.portraitUp,
      DeviceOrientation.portraitDown,
    ]);
    // Full-screen immersive — mobile only
    SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
      statusBarColor:           Colors.transparent,
      statusBarIconBrightness:  Brightness.light,
      systemNavigationBarColor: Color(0xFF0A0A0F),
    ));
  }
  runApp(const SubtitleApp());
}

// ── App Root ──────────────────────────────────────────────
class SubtitleApp extends StatelessWidget {
  const SubtitleApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title:                  'Live Subtitles',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      brightness:       Brightness.dark,
      scaffoldBackgroundColor: const Color(0xFF0A0A0F),
      colorScheme: const ColorScheme.dark(
        primary:   Color(0xFF00D4FF),
        secondary: Color(0xFF8B5CF6),
      ),
      fontFamily: 'Roboto',
    ),
    home: const SubtitleScreen(),
  );
}

// ── Subtitle entry model ──────────────────────────────────
class SubtitleEntry {
  final int    id;
  final String text;
  final String source;
  final double? confidence;
  final DateTime timestamp;

  const SubtitleEntry({
    required this.id,
    required this.text,
    required this.source,
    this.confidence,
    required this.timestamp,
  });

  factory SubtitleEntry.fromMap(Map<String, dynamic> m, int fallbackId) {
    return SubtitleEntry(
      id:         m['id']         ?? fallbackId,
      text:       m['text']?.toString() ?? '',
      source:     m['source']     ?? 'whisper',
      confidence: m['confidence'] != null ? (m['confidence'] as num).toDouble() : null,
      timestamp:  m['timestamp']  != null
                  ? DateTime.tryParse(m['timestamp']) ?? DateTime.now()
                  : DateTime.now(),
    );
  }
}

// ── Main Screen ───────────────────────────────────────────
class SubtitleScreen extends StatefulWidget {
  const SubtitleScreen({super.key});

  @override
  State<SubtitleScreen> createState() => _SubtitleScreenState();
}

class _SubtitleScreenState extends State<SubtitleScreen>
    with TickerProviderStateMixin {

  // Socket
  IO.Socket? _socket;
  bool       _connected = false;

  // Subtitle state
  SubtitleEntry? _current;
  final List<SubtitleEntry> _history = [];
  int _localCounter = 0;

  // View
  bool _showHistory   = false;
  bool _showSettings  = false;
  double _fontSize    = 28.0;
  bool _showTimestamp = true;
  bool _showSource    = true;

  // Animation
  late AnimationController _flashCtrl;
  late Animation<Color?>    _flashAnim;

  @override
  void initState() {
    super.initState();

    _flashCtrl = AnimationController(
      vsync:    this,
      duration: const Duration(milliseconds: 600),
    );
    _flashAnim = ColorTween(
      begin: const Color(0xFF00D4FF),
      end:   Colors.white,
    ).animate(CurvedAnimation(parent: _flashCtrl, curve: Curves.easeOut));

    _connectSocket();
  }

  // ── Socket connection ─────────────────────────────────
  void _connectSocket() {
    final url = 'http://$SERVER_IP:$SERVER_PORT';

    _socket = IO.io(url,
      IO.OptionBuilder()
        .setTransports(['websocket'])
        .setQuery({'type': 'flutter'})
        .enableAutoConnect()
        .enableReconnection()
        .setReconnectionAttempts(double.infinity)
        .setReconnectionDelay(2000)
        .build(),
    );

    _socket!.onConnect((_) {
      setState(() => _connected = true);
    });

    _socket!.onDisconnect((_) {
      setState(() => _connected = false);
    });

    _socket!.on('subtitle', (data) {
      _handleSubtitle(data);
    });

    _socket!.on('history', (data) {
      if (data is List) {
        setState(() {
          for (final item in data) {
            if (item is Map<String, dynamic>) {
              _history.add(SubtitleEntry.fromMap(item, ++_localCounter));
            }
          }
        });
      }
    });
  }

  void _handleSubtitle(dynamic data) {
    _localCounter++;
    SubtitleEntry entry;

    if (data is Map<String, dynamic>) {
      entry = SubtitleEntry.fromMap(data, _localCounter);
    } else {
      entry = SubtitleEntry(
        id: _localCounter, text: data.toString(),
        source: 'whisper', timestamp: DateTime.now(),
      );
    }

    if (entry.text.isEmpty) return;

    setState(() {
      _current = entry;
      _history.insert(0, entry);
      if (_history.length > 100) _history.removeLast();
    });

    // Flash animation
    _flashCtrl.forward(from: 0);

    // Haptic
    HapticFeedback.lightImpact();
  }

  @override
  void dispose() {
    _flashCtrl.dispose();
    _socket?.dispose();
    super.dispose();
  }

  // ── Build ─────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0F),
      body: SafeArea(
        child: _showHistory ? _buildHistoryView() : _buildLiveView(),
      ),
    );
  }

  // ── Live subtitle view ────────────────────────────────
  Widget _buildLiveView() {
    return Column(
      children: [
        _buildTopBar(),
        Expanded(child: _buildSubtitleDisplay()),
        _buildBottomBar(),
      ],
    );
  }

  Widget _buildTopBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        children: [
          // Connection dot
          AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            width: 8, height: 8,
            decoration: BoxDecoration(
              color:  _connected ? const Color(0xFF10B981) : const Color(0xFFEF4444),
              shape:  BoxShape.circle,
              boxShadow: _connected ? [BoxShadow(
                color: const Color(0xFF10B981).withOpacity(0.5),
                blurRadius: 6,
              )] : [],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            _connected ? 'Live' : 'Connecting…',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.1,
              color: _connected
                ? const Color(0xFF10B981)
                : const Color(0xFF6B7280),
            ),
          ),
          const Spacer(),
          Text(
            '🎤 Live Subtitles',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: Color(0xFF9CA3AF),
              letterSpacing: 0.04,
            ),
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.settings_outlined, size: 20, color: Color(0xFF6B7280)),
            onPressed: () => setState(() => _showSettings = !_showSettings),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
          ),
        ],
      ),
    );
  }

  Widget _buildSubtitleDisplay() {
    return GestureDetector(
      onDoubleTap: () => setState(() => _showHistory = true),
      child: Container(
        width:   double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 40),
        child:   Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_showSettings) _buildSettings(),
            const Spacer(),

            // Eyebrow
            if (_current != null)
              Text(
                '▶  LIVE',
                style: const TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.2,
                  color: Color(0xFF00D4FF),
                ),
              ),

            const SizedBox(height: 16),

            // Main subtitle text
            AnimatedBuilder(
              animation: _flashAnim,
              builder: (_, __) => AnimatedDefaultTextStyle(
                duration: const Duration(milliseconds: 200),
                style: TextStyle(
                  fontSize:   _fontSize,
                  fontWeight: FontWeight.w700,
                  height:     1.35,
                  letterSpacing: -0.02,
                  color: _current != null
                    ? (_flashCtrl.isAnimating ? _flashAnim.value! : Colors.white)
                    : const Color(0xFF374151),
                ),
                child: Text(
                  _current?.text ?? 'Waiting for subtitles…',
                  textAlign: TextAlign.center,
                ),
              ),
            ),

            const SizedBox(height: 16),

            // Meta info
            if (_current != null && (_showTimestamp || _showSource))
              _buildMeta(_current!),

            const Spacer(),
          ],
        ),
      ),
    );
  }

  Widget _buildMeta(SubtitleEntry e) {
    final parts = <String>[];
    if (_showSource) {
      final conf = e.confidence != null
        ? ' ${(e.confidence! * 100).toStringAsFixed(0)}%'
        : '';
      parts.add('${e.source}$conf');
    }
    if (_showTimestamp) {
      final t = e.timestamp;
      parts.add('${t.hour.toString().padLeft(2,'0')}:${t.minute.toString().padLeft(2,'0')}:${t.second.toString().padLeft(2,'0')}');
    }
    return Text(
      parts.join('  ·  '),
      style: const TextStyle(
        fontSize: 11, color: Color(0xFF6B7280),
        letterSpacing: 0.05,
        fontFamily: 'monospace',
      ),
    );
  }

  Widget _buildSettings() {
    return Container(
      margin:  const EdgeInsets.only(bottom: 24),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color:        const Color(0xFF12121A),
        borderRadius: BorderRadius.circular(12),
        border:       Border.all(color: const Color(0xFF1F2937)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Settings', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: Color(0xFF9CA3AF), letterSpacing: 0.08)),
          const SizedBox(height: 12),
          Row(children: [
            const Text('Font size', style: TextStyle(fontSize: 13, color: Color(0xFFD1D5DB))),
            const Spacer(),
            Slider(
              value:    _fontSize,
              min: 16, max: 48, divisions: 8,
              activeColor: const Color(0xFF00D4FF),
              onChanged: (v) => setState(() => _fontSize = v),
            ),
            Text('${_fontSize.toInt()}', style: const TextStyle(fontSize: 12, color: Color(0xFF6B7280), fontFamily: 'monospace')),
          ]),
          _settingsToggle('Show timestamp', _showTimestamp, (v) => setState(() => _showTimestamp = v)),
          _settingsToggle('Show source',    _showSource,    (v) => setState(() => _showSource    = v)),
        ],
      ),
    );
  }

  Widget _settingsToggle(String label, bool value, ValueChanged<bool> onChanged) {
    return Row(
      children: [
        Text(label, style: const TextStyle(fontSize: 13, color: Color(0xFFD1D5DB))),
        const Spacer(),
        Switch(
          value:       value,
          onChanged:   onChanged,
          activeColor: const Color(0xFF00D4FF),
        ),
      ],
    );
  }

  Widget _buildBottomBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: Color(0xFF1F2937))),
      ),
      child: Row(
        children: [
          // Subtitle counter
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color:        const Color(0xFF12121A),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              '#${_history.length}',
              style: const TextStyle(fontSize: 11, color: Color(0xFF6B7280), fontFamily: 'monospace'),
            ),
          ),
          const Spacer(),
          // History button
          TextButton.icon(
            onPressed: () => setState(() => _showHistory = true),
            icon:  const Icon(Icons.history, size: 16, color: Color(0xFF00D4FF)),
            label: const Text('History', style: TextStyle(fontSize: 12, color: Color(0xFF00D4FF))),
          ),
        ],
      ),
    );
  }

  // ── History view ──────────────────────────────────────
  Widget _buildHistoryView() {
    return Column(
      children: [
        // Header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xFF1F2937)))),
          child: Row(
            children: [
              IconButton(
                icon: const Icon(Icons.arrow_back_ios, size: 18, color: Color(0xFF9CA3AF)),
                onPressed: () => setState(() => _showHistory = false),
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
              ),
              const SizedBox(width: 12),
              const Text('Subtitle History', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const Spacer(),
              Text('${_history.length} items', style: const TextStyle(fontSize: 11, color: Color(0xFF6B7280))),
            ],
          ),
        ),
        // List
        Expanded(
          child: _history.isEmpty
            ? const Center(
                child: Text('No history yet', style: TextStyle(color: Color(0xFF6B7280), fontSize: 13)),
              )
            : ListView.separated(
                padding: const EdgeInsets.symmetric(vertical: 8),
                itemCount: _history.length,
                separatorBuilder: (_, __) => const Divider(height: 1, color: Color(0xFF1F2937)),
                itemBuilder: (_, i) {
                  final e = _history[i];
                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          _sourceChip(e.source),
                          const Spacer(),
                          Text(
                            '${e.timestamp.hour.toString().padLeft(2,'0')}:${e.timestamp.minute.toString().padLeft(2,'0')}:${e.timestamp.second.toString().padLeft(2,'0')}',
                            style: const TextStyle(fontSize: 10, color: Color(0xFF6B7280), fontFamily: 'monospace'),
                          ),
                        ]),
                        const SizedBox(height: 6),
                        Text(e.text, style: const TextStyle(fontSize: 15, height: 1.4)),
                      ],
                    ),
                  );
                },
              ),
        ),
      ],
    );
  }

  Widget _sourceChip(String source) {
    final Map<String, Color> colors = {
      'whisper': const Color(0xFF00D4FF),
      'matched': const Color(0xFF8B5CF6),
      'test':    const Color(0xFFF59E0B),
    };
    final color = colors[source] ?? const Color(0xFF6B7280);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color:        color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(4),
        border:       Border.all(color: color.withOpacity(0.3)),
      ),
      child: Text(source, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: color, letterSpacing: 0.06)),
    );
  }
}
