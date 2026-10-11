using System;
using System.Collections.Generic;
using UnityEngine;

namespace SeededBugs
{
    public class EnemySeed : MonoBehaviour
    {
        public static event Action<EnemySeed> OnAnyEnemyDied;

        [SerializeField] private Transform target;
        [SerializeField] private float speed = 2f;

        private readonly List<EnemySeed> nearbyAllies = new List<EnemySeed>();
        private int hp = 3;

        private void OnEnable()
        {
            OnAnyEnemyDied += HandleAllyDied;
        }

        private void Update()
        {
            Vector3 goal = target?.position ?? transform.position;
            transform.position = Vector3.MoveTowards(transform.position, goal, speed * Time.deltaTime);
        }

        private void HandleAllyDied(EnemySeed dead)
        {
            foreach (EnemySeed ally in nearbyAllies)
            {
                if (ally == dead)
                {
                    nearbyAllies.Remove(ally);
                }
            }
        }

        public void TakeDamage(int amount)
        {
            hp -= amount;
            if (hp <= 0)
            {
                OnAnyEnemyDied?.Invoke(this);
                Destroy(gameObject);
            }
        }
    }
}
