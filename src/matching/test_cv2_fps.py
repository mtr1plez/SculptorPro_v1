import cv2

video_paths = [
    "/Users/morgana/Downloads/Dune (2021) [1080p] [WEBRip] [5.1] [YTS.MX]/Dune.2021.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4",
    "/Users/morgana/Downloads/Dune Part Two (2024) [1080p] [WEBRip] [YTS.MX]/Dune.Part.Two.2024.1080p.WEBRip.x264.AAC-[YTS.MX].mp4"
]

for p in video_paths:
    cap = cv2.VideoCapture(p)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Path: {p}\nFPS: {fps}, Frames: {frames}")
    cap.release()
