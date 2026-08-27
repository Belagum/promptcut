using System;
using System.Collections.Generic;

namespace ScriptPortal.Vegas
{
    public enum VideoFieldOrder { None, ProgressiveScan, UpperFieldFirst, LowerFieldFirst }
    public enum VideoKeyframeType { Hold, Linear, Fast, Slow, Smooth, Sharp }
    public enum EnvelopeType { Volume, Pan, Mute, Composite, FadeToColor, Velocity, TransitionProgress }

    public class Timecode
    {
        public static Timecode FromSeconds(double s) { return new Timecode(); }
    }

    public class VideoProperties
    {
        public int Width { get; set; }
        public int Height { get; set; }
        public double FrameRate { get; set; }
        public VideoFieldOrder FieldOrder { get; set; }
        public double PixelAspectRatio { get; set; }
    }

    public class Marker
    {
        public Marker(Timecode position, string label) { }
    }

    public class Markers : List<Marker> { }

    public class Media
    {
        public VideoStream GetVideoStreamByIndex(int i) { return new VideoStream(); }
        public AudioStream GetAudioStreamByIndex(int i) { return new AudioStream(); }
    }

    public class MediaStream { }
    public class VideoStream : MediaStream { }
    public class AudioStream : MediaStream { }

    public class MediaPool
    {
        public Media AddMedia(string path) { return new Media(); }
    }

    public class Take
    {
        public Take(MediaStream stream) { }
        public Timecode Offset { get; set; }
    }

    public class Takes : List<Take> { }

    public class Fade
    {
        public Timecode Length { get; set; }
        public float Gain { get; set; }
    }

    public class VideoMotionVertex
    {
        public VideoMotionVertex(float x, float y) { }
    }

    public class VideoMotionBounds
    {
        public VideoMotionBounds(VideoMotionVertex tl, VideoMotionVertex tr, VideoMotionVertex br, VideoMotionVertex bl) { }
    }

    public class VideoMotionKeyframe
    {
        public VideoMotionKeyframe(Project project, Timecode position) { }
        public VideoMotionBounds Bounds { get; set; }
        public VideoKeyframeType Type { get; set; }
    }

    public class VideoMotionKeyframes : List<VideoMotionKeyframe> { }

    public class VideoMotion
    {
        public VideoMotionKeyframes Keyframes = new VideoMotionKeyframes();
    }

    public class TrackEvent
    {
        public Takes Takes = new Takes();
        public Fade FadeIn = new Fade();
        public Fade FadeOut = new Fade();
        public double PlaybackRate { get; set; }
    }

    public class VideoEvent : TrackEvent
    {
        public VideoEvent(Project project, Timecode start, Timecode length, string name) { }
        public VideoMotion VideoMotion = new VideoMotion();
    }

    public class AudioEvent : TrackEvent
    {
        public AudioEvent(Project project, Timecode start, Timecode length, string name) { }
    }

    public class TrackEvents : List<TrackEvent> { }

    public class EnvelopePoint
    {
        public EnvelopePoint(Timecode position, double y) { }
        public double Y { get; set; }
    }

    public class EnvelopePoints : List<EnvelopePoint> { }

    public class Envelope
    {
        public Envelope(EnvelopeType type) { Points.Add(new EnvelopePoint(new Timecode(), 1.0)); }
        public EnvelopePoints Points = new EnvelopePoints();
    }

    public class Envelopes : List<Envelope> { }

    public class Track
    {
        public TrackEvents Events = new TrackEvents();
    }

    public class VideoTrack : Track
    {
        public VideoTrack(Project project, int index, string name) { }
    }

    public class AudioTrack : Track
    {
        public AudioTrack(Project project, int index, string name) { }
        public Envelopes Envelopes = new Envelopes();
    }

    public class Tracks : List<Track> { }

    public class Project
    {
        public VideoProperties Video = new VideoProperties();
        public Tracks Tracks = new Tracks();
        public MediaPool MediaPool = new MediaPool();
        public Markers Markers = new Markers();
    }

    public class Vegas
    {
        public Project Project = new Project();
        public void SaveProject(string path) { }
    }
}
