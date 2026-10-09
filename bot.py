
import os
import sqlite3
import discord
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing!")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

db = sqlite3.connect("scrims.db")
db.execute("""
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    p1 TEXT NOT NULL,
    p2 TEXT NOT NULL,
    p3 TEXT NOT NULL,
    p4 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    UNIQUE(guild_id, group_name, team_name)
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    placement INTEGER NOT NULL,
    kills INTEGER NOT NULL
)
""")
db.commit()

PLACEMENT_POINTS = {
    1: 12, 2: 9, 3: 8, 4: 7, 5: 6, 6: 5,
    7: 4, 8: 3, 9: 2, 10: 1, 11: 0, 12: 0
}


def is_admin(interaction):
    return interaction.guild is not None and (
        interaction.user.guild_permissions.manage_guild
        or interaction.user.guild_permissions.administrator
    )


@tree.command(name="register", description="Register a scrims team")
@app_commands.describe(
    group="Group name, for example Group 1",
    team_name="Your team name",
    player1="Player 1 IGN",
    player2="Player 2 IGN",
    player3="Player 3 IGN",
    player4="Player 4 IGN"
)
async def register(
    interaction: discord.Interaction,
    group: str,
    team_name: str,
    player1: str,
    player2: str,
    player3: str,
    player4: str
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Register inside the scrims server.", ephemeral=True)
        return

    group = group.strip()
    team_name = team_name.strip()
    players = [player1.strip(), player2.strip(),
               player3.strip(), player4.strip()]

    if not group or not team_name or any(not p for p in players):
        await interaction.response.send_message(
            "All fields are required.", ephemeral=True)
        return

    guild_id = interaction.guild.id

    count = db.execute("""
        SELECT COUNT(*) FROM teams
        WHERE guild_id=? AND group_name=?
        AND status IN ('Pending', 'Approved')
    """, (guild_id, group)).fetchone()[0]

    if count >= 12:
        await interaction.response.send_message(
            f"{group} is full (12 teams).", ephemeral=True)
        return

    try:
        db.execute("""
            INSERT INTO teams
            (guild_id, group_name, team_name, p1, p2, p3, p4)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, group, team_name, *players))
        db.commit()
    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            "That team name is already registered in this group.",
            ephemeral=True)
        return

    await interaction.response.send_message(
        f"Registration received for **{team_name}** in **{group}**. "
        "Status: Pending admin approval.",
        ephemeral=True
    )


@tree.command(name="pending", description="List pending registrations")
@app_commands.describe(group="Group to check")
async def pending(interaction: discord.Interaction, group: str):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "Admin only.", ephemeral=True)
        return

    rows = db.execute("""
        SELECT id, team_name, p1, p2, p3, p4 FROM teams
        WHERE guild_id=? AND group_name=? AND status='Pending'
        ORDER BY id
    """, (interaction.guild.id, group.strip())).fetchall()

    if not rows:
        await interaction.response.send_message(
            "No pending teams in this group.", ephemeral=True)
        return

    lines = [
        f"ID {r[0]} | **{r[1]}** | IGN: {r[2]}, {r[3]}, {r[4]}, {r[5]}"
        for r in rows
    ]
    await interaction.response.send_message(
        "\n".join(lines), ephemeral=True)


@tree.command(name="approve", description="Approve a team by ID")
async def approve(interaction: discord.Interaction, team_id: int):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "Admin only.", ephemeral=True)
        return

    cur = db.execute("""
        UPDATE teams SET status='Approved'
        WHERE id=? AND guild_id=? AND status='Pending'
    """, (team_id, interaction.guild.id))
    db.commit()

    await interaction.response.send_message(
        "Team approved!" if cur.rowcount else
        "Pending team ID not found.")


@tree.command(name="reject", description="Reject a team by ID")
async def reject(interaction: discord.Interaction, team_id: int):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "Admin only.", ephemeral=True)
        return

    cur = db.execute("""
        UPDATE teams SET status='Rejected'
        WHERE id=? AND guild_id=? AND status='Pending'
    """, (team_id, interaction.guild.id))
    db.commit()

    await interaction.response.send_message(
        "Team rejected." if cur.rowcount else
        "Pending team ID not found.")


@tree.command(name="teams", description="Show approved teams in a group")
async def teams(interaction: discord.Interaction, group: str):
    rows = db.execute("""
        SELECT team_name, p1, p2, p3, p4 FROM teams
        WHERE guild_id=? AND group_name=? AND status='Approved'
        ORDER BY id
    """, (interaction.guild.id, group.strip())).fetchall()

    if not rows:
        await interaction.response.send_message(
            "No approved teams in this group.")
        return

    lines = [
        f"**{i}. {r[0]}** — {r[1]}, {r[2]}, {r[3]}, {r[4]}"
        for i, r in enumerate(rows, 1)
    ]
    await interaction.response.send_message(
        f"**{group} — Approved Teams**\n" + "\n".join(lines))


@tree.command(name="result", description="Add a team's match result")
@app_commands.describe(
    group="Group name",
    team_name="Approved team name",
    placement="Final placement from 1 to 12",
    kills="Total kills"
)
async def result(
    interaction: discord.Interaction,
    group: str,
    team_name: str,
    placement: app_commands.Range[int, 1, 12],
    kills: app_commands.Range[int, 0, 999]
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "Admin only.", ephemeral=True)
        return

    team = db.execute("""
        SELECT 1 FROM teams
        WHERE guild_id=? AND group_name=? AND team_name=?
        AND status='Approved'
    """, (interaction.guild.id, group.strip(),
          team_name.strip())).fetchone()

    if not team:
        await interaction.response.send_message(
            "Approved team not found in this group.", ephemeral=True)
        return

    db.execute("""
        INSERT INTO results
        (guild_id, group_name, team_name, placement, kills)
        VALUES (?, ?, ?, ?, ?)
    """, (interaction.guild.id, group.strip(), team_name.strip(),
          placement, kills))
    db.commit()

    points = PLACEMENT_POINTS[placement] + kills
    await interaction.response.send_message(
        f"Result saved: **{team_name}** | "
        f"Placement: {placement} | Kills: {kills} | "
        f"Points: {points}")


@tree.command(name="leaderboard", description="Show group points table")
async def leaderboard(interaction: discord.Interaction, group: str):
    rows = db.execute("""
        SELECT t.team_name,
        COALESCE(SUM(
            CASE r.placement
                WHEN 1 THEN 12 WHEN 2 THEN 9 WHEN 3 THEN 8
                WHEN 4 THEN 7 WHEN 5 THEN 6 WHEN 6 THEN 5
                WHEN 7 THEN 4 WHEN 8 THEN 3 WHEN 9 THEN 2
                WHEN 10 THEN 1 ELSE 0
            END + r.kills
        ), 0) AS points,
        COALESCE(SUM(r.kills), 0) AS kills
        FROM teams t
        LEFT JOIN results r
          ON r.guild_id=t.guild_id
          AND r.group_name=t.group_name
          AND r.team_name=t.team_name
        WHERE t.guild_id=? AND t.group_name=?
          AND t.status='Approved'
        GROUP BY t.team_name
        ORDER BY points DESC, kills DESC, t.team_name ASC
    """, (interaction.guild.id, group.strip())).fetchall()

    if not rows:
        await interaction.response.send_message(
            "No approved teams in this group.")
        return

    lines = [
        f"**{i}. {r[0]}** — {r[1]} points ({r[2]} kills)"
        for i, r in enumerate(rows, 1)
    ]
    await interaction.response.send_message(
        f"🏆 **{group} Leaderboard**\n" + "\n".join(lines))


@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot online: {client.user}")


client.run(TOKEN)
