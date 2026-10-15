import asyncio
import edge_tts

tests = [
    'Здравствуйте дорогие зрители',
    'дорогие зрители нашего аналитического канала',
    'Здравствуйте',
    'Приветствую вас, дорогие зрители нашего аналитического канала',
    'В Берлине началась тревога из за провала стратегии'
]

async def run():
    for t in tests:
        try:
            c = edge_tts.Communicate(text=t, voice='ru-RU-DmitryNeural')
            b = bytearray()
            async for ch in c.stream():
                if ch['type'] == 'audio':
                    b.extend(ch['data'])
            print(f'OK ({len(b)}b): {t}')
        except Exception as e:
            print(f'FAIL: {t}')

if __name__ == '__main__':
    asyncio.run(run())
