"""Three small games written for this GPU, using only the graphics API. All original.

Usage: python -m sw.dtgc play kart|pong|maze|dodge

Each game has step(keys), which moves the game on by one frame, and draw(canvas). keys is a set of names:
"up", "down", "left", "right". Nothing depends on the clock or the picture, so tests can replay a game exactly.
demo_keys() returns what the game would press to play itself, for the recordings on the microSD card (sw/dtgc/sdcard.py).
FPS is the frame rate a game is made for. The kart race is in kart.py.
"""
import math
import random
from collections import deque

from .api import HEIGHT, WIDTH, Canvas, Mesh, rgb, text_width
from .kart import KartRace

WHITE = rgb(255, 255, 255)
DARK_BLUE = rgb(0, 0, 85)  # blue has only 2 bits: anything under 64 comes out black


class Pong:
    """The player's paddle is on the left, up and down to move. First to 5 wins."""
    PADDLE_W, PADDLE_H, BALL, TOP = 8, 50, 8, 30
    WIN_SCORE = 5
    CPU_SPEED = 3
    FPS = 30

    def __init__(self, seed=1):
        self.random = random.Random(seed)
        self.player_y = self.cpu_y = (HEIGHT - self.PADDLE_H) // 2
        self.player_score = self.cpu_score = 0
        self.over = False
        self._serve(1)

    def _serve(self, direction):
        self.ball_x, self.ball_y = (WIDTH - self.BALL) // 2, (HEIGHT - self.BALL) // 2
        self.speed_x = 4 * direction
        self.speed_y = self.random.choice((-3, -2, 2, 3))

    def step(self, keys):
        if self.over:
            return
        move = (("down" in keys) - ("up" in keys)) * 6
        self.player_y = self._limit_paddle(self.player_y + move)
        # The CPU follows the ball, but slower than a steep ball can move, which is what makes it beatable.
        gap = self.ball_y + self.BALL // 2 - (self.cpu_y + self.PADDLE_H // 2)
        self.cpu_y = self._limit_paddle(self.cpu_y + max(-self.CPU_SPEED, min(self.CPU_SPEED, gap)))
        self.ball_x += self.speed_x
        self.ball_y += self.speed_y
        if self.ball_y < self.TOP:
            self.ball_y, self.speed_y = self.TOP, -self.speed_y
        if self.ball_y > HEIGHT - self.BALL:
            self.ball_y, self.speed_y = HEIGHT - self.BALL, -self.speed_y
        if self.speed_x < 0 and self.ball_x <= 14 + self.PADDLE_W and self._hits(self.player_y):
            self._bounce(self.player_y, 1)
        elif self.speed_x > 0 and self.ball_x + self.BALL >= WIDTH - 14 - self.PADDLE_W and self._hits(self.cpu_y):
            self._bounce(self.cpu_y, -1)
        if self.ball_x < -self.BALL:
            self.cpu_score += 1
            self._serve(-1)
        elif self.ball_x > WIDTH:
            self.player_score += 1
            self._serve(1)
        self.over = max(self.player_score, self.cpu_score) >= self.WIN_SCORE

    def demo_keys(self):
        """Follows the ball, a little late, so the computer side still wins points now and then."""
        gap = self.ball_y + self.BALL // 2 - (self.player_y + self.PADDLE_H // 2) + self.random.randint(-14, 14)
        return {"down"} if gap > 6 else {"up"} if gap < -6 else set()

    def _limit_paddle(self, y):
        return max(self.TOP, min(HEIGHT - self.PADDLE_H, y))

    def _hits(self, paddle_y):
        return paddle_y - self.BALL < self.ball_y < paddle_y + self.PADDLE_H

    def _bounce(self, paddle_y, direction):
        self.speed_x = direction * min(9, abs(self.speed_x) + 1)
        # A hit away from the paddle's middle adds to the ball's angle, so a long rally gets steeper and ends.
        spin = (self.ball_y + self.BALL // 2 - paddle_y - self.PADDLE_H // 2) // 4
        self.speed_y = max(-8, min(8, self.speed_y + spin)) or 1
        self.ball_x = 14 + self.PADDLE_W if direction > 0 else WIDTH - 14 - self.PADDLE_W - self.BALL

    def draw(self, canvas):
        canvas.clear(DARK_BLUE)
        canvas.rect(0, self.TOP - 3, WIDTH, 2, WHITE)
        canvas.text(WIDTH * 100 // 340, 6, str(self.player_score), WHITE, 3)
        canvas.text(WIDTH * 230 // 340, 6, str(self.cpu_score), WHITE, 3)
        canvas.rect(14, self.player_y, self.PADDLE_W, self.PADDLE_H, rgb(80, 255, 120))
        canvas.rect(WIDTH - 14 - self.PADDLE_W, self.cpu_y, self.PADDLE_W, self.PADDLE_H, rgb(255, 120, 80))
        canvas.rect(self.ball_x, self.ball_y, self.BALL, self.BALL, WHITE)
        if self.over:
            message = "YOU WIN" if self.player_score > self.cpu_score else "YOU LOSE"
            canvas.text((WIDTH - text_width(message, 4)) // 2, HEIGHT * 150 // 340, message, WHITE, 4)


MAZE_MAP = (
    "################",
    "#..#.......#...#",
    "#..#.###.#.#.#.#",
    "#....#...#...#.#",
    "###.##.#####.#.#",
    "#......#.....#.#",
    "#.####.#.#####.#",
    "#.#....#.......#",
    "#.#.######.###.#",
    "#...#......#...#",
    "#####.####.#.###",
    "#.....#....#...X",
    "################",
)


class Maze:
    """Find the bright exit. Left and right turn, up and down walk. Walls are one RECT per screen column."""
    COLUMN = 4
    TURN = 0.08
    WALK = 0.09
    BODY = 0.25
    STRIPES = 4
    FPS = 30

    def __init__(self):
        self.x, self.y, self.angle = 1.5, 1.5, 0.3
        self.won = False

    @staticmethod
    def _cell(x, y):
        row, column = int(y), int(x)
        if 0 <= row < len(MAZE_MAP) and 0 <= column < len(MAZE_MAP[0]):
            return MAZE_MAP[row][column]
        return "#"

    def step(self, keys):
        if self.won:
            return
        self.angle += (("right" in keys) - ("left" in keys)) * self.TURN
        distance = (("up" in keys) - ("down" in keys)) * self.WALK
        new_x = self.x + math.cos(self.angle) * distance
        new_y = self.y + math.sin(self.angle) * distance
        # Moving each way on its own lets the player slide along a wall.
        if self._free(new_x, self.y):
            self.x = new_x
        if self._free(self.x, new_y):
            self.y = new_y
        self.won = self._cell(self.x, self.y) == "X"

    def demo_keys(self):
        """Walks the shortest way out: turns to face the middle of the next cell on the path, then walks."""
        start, goal = (int(self.x), int(self.y)), None
        came = {start: None}
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if self._cell(cell[0] + 0.5, cell[1] + 0.5) == "X":
                goal = cell
                break
            for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                after = (cell[0] + step[0], cell[1] + step[1])
                if after not in came and self._cell(after[0] + 0.5, after[1] + 0.5) != "#":
                    came[after] = cell
                    queue.append(after)
        if goal is None or goal == start:
            return {"up"}
        while came[goal] != start:
            goal = came[goal]
        wanted = math.atan2(goal[1] + 0.5 - self.y, goal[0] + 0.5 - self.x)
        error = (wanted - self.angle + math.pi) % math.tau - math.pi
        keys = {"right"} if error > self.TURN else {"left"} if error < -self.TURN else set()
        if abs(error) < 0.6:
            keys.add("up")
        return keys

    def _free(self, x, y):
        """The player is a square BODY from the middle to each side, so the view never ends up inside a wall."""
        return all(self._cell(x + i * self.BODY, y + j * self.BODY) != "#" for i in (-1, 1) for j in (-1, 1))

    def _cast(self, angle):
        """Walks the grid one cell edge at a time.

        Returns (distance, hit a side facing east or west, cell, how far along the wall from 0 to 1).
        """
        dx, dy = math.cos(angle), math.sin(angle)
        cell_x, cell_y = int(self.x), int(self.y)
        step_x, step_y = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
        delta_x, delta_y = abs(1 / dx) if dx else 1e9, abs(1 / dy) if dy else 1e9
        next_x = ((cell_x + 1 - self.x) if dx > 0 else (self.x - cell_x)) * delta_x
        next_y = ((cell_y + 1 - self.y) if dy > 0 else (self.y - cell_y)) * delta_y
        for _ in range(64):
            if next_x < next_y:
                cell_x += step_x
                distance, side = next_x, True
                next_x += delta_x
            else:
                cell_y += step_y
                distance, side = next_y, False
                next_y += delta_y
            kind = self._cell(cell_x + 0.5, cell_y + 0.5)
            if kind != ".":
                along = self.y + dy * distance if side else self.x + dx * distance
                return distance, side, kind, along % 1.0
        return 64.0, True, "#", 0.0

    def draw(self, canvas):
        canvas.clear(rgb(40, 40, 85))
        canvas.rect(0, HEIGHT // 2, WIDTH, HEIGHT // 2, rgb(70, 50, 0))
        for column in range(0, WIDTH, self.COLUMN):
            offset = math.atan((column + self.COLUMN / 2 - WIDTH / 2) / 220)
            distance, side, kind, along = self._cast(self.angle + offset)
            height = int(min(HEIGHT, 220 * HEIGHT / 340 / max(0.05, distance * math.cos(offset))))
            bright = max(40, int(255 - distance * 22))
            # Stripes, so a wall right in front of the player still shows which way it runs.
            if int(along * self.STRIPES) % 2:
                bright = bright * 2 // 3
            if kind == "X":
                color = rgb(80, 255, 80)
            else:
                color = rgb(bright, bright * 3 // 5, bright // 3) if side else rgb(bright * 3 // 4, bright // 2, bright // 4)
            canvas.rect(column, (HEIGHT - height) // 2, self.COLUMN, height, color)
        if self.won:
            canvas.text((WIDTH - text_width("YOU ESCAPED", 3)) // 2, HEIGHT * 150 // 340, "YOU ESCAPED", WHITE, 3)


class Dodge:
    """Fly between cubes coming towards you. Arrows move. Real 3D: depth-tested triangles from the GPU."""
    ROCKS = 6
    LANE = 3.0
    FAR = 30.0
    FPS = 30

    def __init__(self, seed=1):
        self.random = random.Random(seed)
        self.x, self.y = 0.0, 0.0
        self.speed = 0.25
        self.score = 0
        self.over = False
        self.frame = 0
        self.mesh = Mesh.cube(0.8)
        self.rocks = [self._new_rock(self.FAR * (i + 1) / self.ROCKS + 8) for i in range(self.ROCKS)]

    def _new_rock(self, z):
        return [self.random.uniform(-self.LANE, self.LANE), self.random.uniform(-self.LANE, self.LANE), z]

    def step(self, keys):
        if self.over:
            return
        self.frame += 1
        self.x += (("right" in keys) - ("left" in keys)) * 0.14
        self.y += (("down" in keys) - ("up" in keys)) * 0.14
        self.x, self.y = max(-self.LANE, min(self.LANE, self.x)), max(-self.LANE, min(self.LANE, self.y))
        self.speed = min(0.6, 0.25 + self.frame * 0.0002)
        for rock in self.rocks:
            rock[2] -= self.speed
            if rock[2] < 1.2:
                self.score += 1
                rock[:] = self._new_rock(self.FAR)
            elif rock[2] < 2.0 and abs(rock[0] - self.x) < 0.9 and abs(rock[1] - self.y) < 0.9:
                self.over = True

    def demo_keys(self):
        """Steers away from the nearest cube that would hit, and drifts back to the middle when the way is clear."""
        danger = [rock for rock in self.rocks if rock[2] < 9 and abs(rock[0] - self.x) < 1.3 and abs(rock[1] - self.y) < 1.3]
        keys = set()
        if danger:
            rock = min(danger, key=lambda r: r[2])
            away_x = self.x - rock[0] or (1 if self.x < 0 else -1)
            away_y = self.y - rock[1] or (1 if self.y < 0 else -1)
            if abs(away_x) <= abs(away_y) or abs(self.x) > self.LANE - 0.3:
                keys.add("down" if away_y > 0 and self.y < self.LANE - 0.3 else "up")
            else:
                keys.add("right" if away_x > 0 else "left")
        elif self.x > 0.3:
            keys.add("left")
        elif self.x < -0.3:
            keys.add("right")
        return keys

    def draw(self, canvas):
        canvas.clear_scene(DARK_BLUE)
        # Any drawing order works: the GPU's depth test sorts the cubes out.
        for rock in self.rocks:
            canvas.draw_mesh(self.mesh, (rock[0] - self.x, rock[1] - self.y, rock[2]), rock[2] * 0.2, rock[2] * 0.3, 0.0)
        canvas.text(8, 8, f"SCORE {self.score}", WHITE)
        if self.over:
            canvas.text((WIDTH - text_width("CRASHED", 4)) // 2, HEIGHT * 150 // 340, "CRASHED", WHITE, 4)


GAMES = {"kart": KartRace, "pong": Pong, "maze": Maze, "dodge": Dodge}


def _key_name(symbol):
    return {"Up": "up", "w": "up", "W": "up", "Down": "down", "s": "down", "S": "down",
            "Left": "left", "a": "left", "A": "left", "Right": "right", "d": "right", "D": "right",
            "space": "fire", "Return": "fire", "x": "fire", "X": "fire"}.get(symbol)


def play(name, gpu, device=None, fps=None, frames=None):
    """Runs a game in a window that takes the keys. With device set (the emulator) it also shows the picture.

    fps defaults to the game's own. frames, if given, stops after that many frames. Otherwise it runs until the window
    is closed. The GPU's SWAP waits for the screen, so on a 30 Hz screen a game made for 60 runs at half speed.
    """
    import tkinter

    game = GAMES[name]()
    fps = fps or getattr(game, "FPS", 30)
    canvas = Canvas(gpu)
    root = tkinter.Tk()
    root.title(f"DTGC {name}")
    held = set()
    root.bind("<KeyPress>", lambda e: held.add(_key_name(e.keysym)))
    root.bind("<KeyRelease>", lambda e: held.discard(_key_name(e.keysym)))
    picture = tkinter.PhotoImage(width=WIDTH, height=HEIGHT) if device else None
    if picture:
        tkinter.Label(root, image=picture).pack()
    else:
        tkinter.Label(root, text="Keep this window selected. Arrows or WASD steer, space uses an item. The game is on the HDMI screen.").pack(padx=20, pady=20)
    count = [0]

    def frame():
        game.step(held)
        game.draw(canvas)
        canvas.show()
        canvas.finish()
        if picture:
            picture.configure(data=f"P6 {WIDTH} {HEIGHT} 255 ".encode() + device.window_rgb(), format="PPM")
        count[0] += 1
        if frames is not None and count[0] >= frames:
            root.destroy()
        else:
            root.after(max(1, 1000 // fps), frame)

    root.after(0, frame)
    root.mainloop()
